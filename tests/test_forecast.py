"""Fast tests for the forecasting pipeline on synthetic data (no database, no MLflow, no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.features import (  # noqa: E402
    FEATURES,
    ComplaintForecaster,
    HorizonModel,
    baseline_forecast,
    build_rows,
    flag_spikes,
    mae,
    mape,
    mase,
    min_origin,
    seasonal_naive,
    seasonal_naive_scale,
    smape,
    training_rows,
    wape,
    week_start,
    weekly_counts,
)


def _records(pairs):
    return pd.DataFrame(pairs, columns=["date_filed", "component_primary"])


def test_week_start_is_monday():
    ws = week_start(pd.Series(pd.to_datetime(["2026-10-12", "2026-10-15", "2026-10-18", "2026-10-19"])))
    assert [d.strftime("%Y-%m-%d") for d in ws] == ["2026-10-12", "2026-10-12", "2026-10-12", "2026-10-19"]


def test_weekly_counts_fills_missing_weeks_and_drops_partial_weeks():
    df = _records([
        ("2024-01-03", "A"),   # Wed: the week starting 2024-01-01 is only partly covered by the data
        ("2024-01-08", "A"),
        ("2024-01-09", "B"),
        ("2024-01-29", "A"),   # weeks 2024-01-15 and 2024-01-22 have no records -> zero rows
        ("2024-02-01", "A"),   # Thu of week 2024-01-29; data ends here so that week is partial
    ])
    wide = weekly_counts(df, min_total=1)
    # first record is Wed 2024-01-03 -> week 2024-01-01 is partial and dropped
    assert wide.index[0] == pd.Timestamp("2024-01-08")
    # data ends Thu 2024-02-01 -> week 2024-01-29 is partial and dropped
    assert wide.index[-1] == pd.Timestamp("2024-01-22")
    assert list(wide.index) == list(pd.date_range("2024-01-08", "2024-01-22", freq="7D"))
    assert wide.loc["2024-01-08", "A"] == 1 and wide.loc["2024-01-08", "B"] == 1
    assert wide.loc["2024-01-15"].sum() == 0 and wide.loc["2024-01-22"].sum() == 0


def test_weekly_counts_keeps_complete_final_week_and_pools_rare_components():
    rows = [("2024-01-01", "BIG")] * 5 + [("2024-01-02", "RARE")] + [("2024-01-07", "OTHER")]
    wide = weekly_counts(_records(rows), min_total=3)
    assert list(wide.index) == [pd.Timestamp("2024-01-01")]   # Sunday 2024-01-07 completes the week
    assert wide.attrs["pooled"] == ["RARE"]
    assert "RARE" not in wide.columns
    assert wide.loc["2024-01-01", "OTHER"] == 2 and wide.loc["2024-01-01", "BIG"] == 5


def test_seasonal_naive_correctness():
    y = np.arange(110, dtype=float)
    f = seasonal_naive(y, 52)
    assert np.isnan(f[:52]).all()
    assert np.array_equal(f[52:], y[:58])
    assert seasonal_naive_scale(y, 52) == pytest.approx(52.0)


def test_feature_rows_match_baseline_definitions():
    weeks = pd.date_range("2022-01-03", periods=80, freq="7D")
    Y = pd.DataFrame({"A": np.arange(80, dtype=float), "B": np.arange(80, dtype=float) * 2}, index=weeks)
    one = build_rows(Y, [70], [1])
    a = one[one["component_name"] == "A"].iloc[0]
    assert a["target_idx"] == 71 and a["y"] == 71
    assert a["lag1"] == 70 and a["lag13"] == 58
    assert a["slag52"] == 71 - 52                         # same week last year
    assert a["roll4"] == pytest.approx(np.mean([67, 68, 69, 70]))
    assert baseline_forecast(one, "snaive52")[0] == 19
    direct = build_rows(Y, [70], [3])
    assert direct.iloc[0]["slag52"] == 73 - 52 and direct.iloc[0]["lag1"] == 70   # no peeking past origin
    assert build_rows(Y, [min_origin(1) - 1], [1]).empty
    tr = training_rows(Y, 75, [1, 2])
    assert tr["target_idx"].max() == 74


def test_metrics_handle_zero_actuals():
    y = np.array([0, 2, 4, 0])
    f = np.array([1, 1, 4, 0])
    assert mape(y, f) == pytest.approx(25.0)                       # zeros skipped: mean(0.5, 0)
    assert np.isnan(mape([0, 0], [1, 2]))
    assert smape(y, f) == pytest.approx((200 + 2 / 3 * 100 + 0 + 0) / 4)
    assert wape(y, f) == pytest.approx(2 / 6 * 100)
    assert mae(y, f) == pytest.approx(0.5)
    assert np.isnan(wape([0, 0], [1, 1]))


def test_mase_scaled_by_seasonal_naive():
    train = np.r_[np.zeros(52), np.full(52, 2.0)]             # in-sample seasonal naive MAE = 2
    assert seasonal_naive_scale(train) == pytest.approx(2.0)
    assert mase([3, 5], [2, 2], 2.0) == pytest.approx(1.0)   # MAE 2 / scale 2
    assert np.isnan(mase([1], [0], 0.0))


def test_spike_rule():
    flag, ratio = flag_spikes([10, 4, 2, 5, 3], [6, 4, 0.5, 8, 0.2], min_count=3)
    assert flag.tolist() == [True, False, False, False, True]   # strictly above; 2 is below min_count
    assert ratio[0] == pytest.approx(10 / 6) and ratio[4] == pytest.approx(3.0)   # upper floored at 1


def test_gbm_forecaster_end_to_end_on_synthetic_panel():
    rng = np.random.default_rng(0)
    weeks = pd.date_range("2022-01-03", periods=120, freq="7D")
    season = 5 + 3 * np.sin(2 * np.pi * np.arange(120) / 52)
    Y = pd.DataFrame({"A": rng.poisson(season), "B": rng.poisson(season * 2)}, index=weeks).astype(float)
    tr = training_rows(Y, 100, [1])
    m1 = HorizonModel(kind="gbm", n_components=2).fit(tr, tr["y"].to_numpy())
    model = ComplaintForecaster(one_step=m1, direct=m1, components=["A", "B"], train_end_week="x")
    rows = build_rows(Y, range(99, 119), [1])
    p, lo, hi = model.predict_interval(rows[FEATURES])
    assert len(p) == 40 and (lo <= p).all() and (p <= hi).all() and (lo >= 0).all()
