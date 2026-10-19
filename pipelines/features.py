"""Weekly aggregation, lag features, baselines, metrics, the forecaster estimators and the spike rule.

Everything here is pure (no database, no MLflow) so it can be unit tested on synthetic data and pickled
inside an MLflow model. `pipelines.forecast` wires these pieces to the database and to MLflow.

Indexing convention: a wide panel `Y` has one row per week (Monday start date) and one column per
component. A supervised row is defined by an origin index `o` (the last week whose actual is known) and a
horizon `h`; its target is week `o + h`. Every feature uses actuals at or before `o` only, except
`slag52*`, which read the same week one year before the target (known whenever h <= 51).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd
from scipy.stats import poisson
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import PoissonRegressor
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler

SEASON = 52
ORIGIN_LAGS = (1, 2, 3, 4, 8, 13)
ROLL_WINDOWS = (4, 8, 13)
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

COUNT_FEATURES = [
    *(f"lag{k}" for k in ORIGIN_LAGS),
    *(f"roll{w}" for w in ROLL_WINDOWS),
    "slag52",
    "slag52_mean3",
    "total_lag1",
    "total_roll4",
]
FEATURES = ["component", "h", *COUNT_FEATURES, "woy_sin", "woy_cos"]

BASELINES = {"naive": "lag1", "snaive52": "slag52", "ma4": "roll4", "ma8": "roll8"}


# --------------------------------------------------------------------------------------------------
# Weekly aggregation
# --------------------------------------------------------------------------------------------------

def week_start(dates: pd.Series | pd.DatetimeIndex, freq: str = "W-MON") -> pd.Series:
    """Start date of the 7-day week containing each date. 'W-MON' means weeks start on Monday."""
    anchor = WEEKDAYS.index(freq.split("-")[1].upper())
    d = pd.to_datetime(pd.Series(dates)).dt.normalize()
    return d - pd.to_timedelta((d.dt.weekday - anchor) % 7, unit="D")


def weekly_counts(
    df: pd.DataFrame,
    date_col: str = "date_filed",
    comp_col: str = "component_primary",
    freq: str = "W-MON",
    min_total: int = 30,
    as_of: str | pd.Timestamp | None = None,
    pooled_label: str = "OTHER",
) -> pd.DataFrame:
    """Wide weekly count panel (index: week start, columns: component), zero-filled.

    Components with fewer than `min_total` records in total are pooled into `pooled_label`. Leading and
    trailing partial weeks are dropped: the last week is kept only if all 7 days are on or before `as_of`
    (default: the latest date in the data). The pooled component names are in `result.attrs["pooled"]`.
    """
    d = df[[date_col, comp_col]].copy()
    d[date_col] = pd.to_datetime(d[date_col])
    d = d.dropna(subset=[date_col])
    as_of = pd.Timestamp(as_of).normalize() if as_of is not None else d[date_col].max().normalize()
    d = d[d[date_col] <= as_of]
    comp = d[comp_col].fillna(pooled_label).astype(str)
    totals = comp.value_counts()
    pooled = sorted(c for c, n in totals.items() if n < min_total and c != pooled_label)
    comp = comp.where(~comp.isin(pooled), pooled_label)

    first_day = d[date_col].min().normalize()
    first_week = week_start(pd.Series([first_day]), freq).iloc[0]
    if first_week < first_day:
        first_week += pd.Timedelta(days=7)
    last_week = week_start(pd.Series([as_of]), freq).iloc[0]
    if last_week + pd.Timedelta(days=6) > as_of:
        last_week -= pd.Timedelta(days=7)
    weeks = pd.date_range(first_week, last_week, freq="7D")

    wk = week_start(d[date_col], freq).to_numpy()
    counts = (
        pd.DataFrame({"week": wk, "component": comp.to_numpy()})
        .groupby(["week", "component"]).size().unstack(fill_value=0)
    )
    cols = sorted(set(counts.columns) | ({pooled_label} if pooled else set()))
    wide = counts.reindex(index=weeks, columns=cols, fill_value=0).astype(float)
    wide.index.name = "week"
    wide.columns.name = None
    wide.attrs["pooled"] = pooled
    return wide


# --------------------------------------------------------------------------------------------------
# Supervised rows
# --------------------------------------------------------------------------------------------------

def min_origin(h: int) -> int:
    """Smallest origin index with every feature defined for horizon h."""
    return max(max(ORIGIN_LAGS) - 1, max(ROLL_WINDOWS) - 1, SEASON + 1 - h)


def build_rows(Y: pd.DataFrame, origins: Iterable[int], horizons: Sequence[int]) -> pd.DataFrame:
    """One row per (origin, horizon, component). Targets past the end of Y get week dates extrapolated by
    7 days and y = NaN (used for future forecasts)."""
    arr = Y.to_numpy(dtype=float)
    T, C = arr.shape
    weeks = Y.index
    comps = np.arange(C)
    blocks = []
    for o in origins:
        for h in horizons:
            if o < min_origin(h) or o >= T:
                continue
            t = o + h
            feats = {
                "component": comps,
                "h": np.full(C, h),
                "origin_idx": np.full(C, o),
                "target_idx": np.full(C, t),
            }
            for k in ORIGIN_LAGS:
                feats[f"lag{k}"] = arr[o + 1 - k]
            for w in ROLL_WINDOWS:
                feats[f"roll{w}"] = arr[o - w + 1 : o + 1].mean(axis=0)
            feats["slag52"] = arr[t - SEASON]
            feats["slag52_mean3"] = arr[t - SEASON - 1 : t - SEASON + 2].mean(axis=0)
            feats["total_lag1"] = np.full(C, arr[o].sum())
            feats["total_roll4"] = np.full(C, arr[o - 3 : o + 1].sum(axis=1).mean())
            week = weeks[t] if t < T else weeks[-1] + pd.Timedelta(days=7 * (t - T + 1))
            woy = week.isocalendar().week
            feats["woy_sin"] = np.full(C, np.sin(2 * np.pi * woy / 52.18))
            feats["woy_cos"] = np.full(C, np.cos(2 * np.pi * woy / 52.18))
            feats["week"] = np.full(C, week)
            feats["y"] = arr[t] if t < T else np.full(C, np.nan)
            blocks.append(pd.DataFrame(feats))
    if not blocks:
        return pd.DataFrame(columns=[*FEATURES, "origin_idx", "target_idx", "week", "y"])
    out = pd.concat(blocks, ignore_index=True)
    out["component_name"] = np.asarray(Y.columns)[out["component"].to_numpy()]
    return out


def training_rows(Y: pd.DataFrame, end_idx: int, horizons: Sequence[int]) -> pd.DataFrame:
    """Rows whose target index is strictly before `end_idx` (no target leakage past the training end)."""
    rows = build_rows(Y.iloc[:end_idx], range(end_idx), horizons)
    return rows[rows["target_idx"] < end_idx].reset_index(drop=True)


# --------------------------------------------------------------------------------------------------
# Baselines and simple exponential smoothing
# --------------------------------------------------------------------------------------------------

def baseline_forecast(rows: pd.DataFrame, name: str) -> np.ndarray:
    """naive = last value at the origin, snaive52 = same week last year, ma4 / ma8 = trailing mean."""
    return rows[BASELINES[name]].to_numpy(dtype=float)


def seasonal_naive(y: Sequence[float], season: int = SEASON) -> np.ndarray:
    """1-step seasonal naive forecasts: f[t] = y[t - season]; NaN for the first `season` points."""
    y = np.asarray(y, dtype=float)
    f = np.full_like(y, np.nan)
    f[season:] = y[:-season]
    return f


def ses_levels(y: np.ndarray, alpha: float, init_n: int = 4) -> np.ndarray:
    """Level after observing y[t] for simple exponential smoothing, initialised at mean(y[:init_n])."""
    level = np.empty(len(y))
    cur = float(np.mean(y[:init_n])) if len(y) else 0.0
    for t, v in enumerate(y):
        cur = alpha * v + (1 - alpha) * cur
        level[t] = cur
    return level


def fit_ses_alpha(y: np.ndarray, grid: Sequence[float] = tuple(np.round(np.arange(0.05, 1.0, 0.05), 2))) -> float:
    """Alpha minimising in-sample 1-step squared error (grid search; no optimiser dependency)."""
    best, best_sse = grid[0], np.inf
    for a in grid:
        lv = ses_levels(y, a)
        sse = float(np.sum((y[5:] - lv[4:-1]) ** 2))
        if sse < best_sse:
            best, best_sse = a, sse
    return float(best)


def ses_forecast(Y: pd.DataFrame, train_end: int, rows: pd.DataFrame) -> tuple[np.ndarray, dict[str, float]]:
    """Per-component SES; alpha fitted on Y[:train_end]; forecast for any horizon is the level at the origin."""
    arr = Y.to_numpy(dtype=float)
    alphas, levels = {}, np.empty_like(arr)
    for j, c in enumerate(Y.columns):
        a = fit_ses_alpha(arr[:train_end, j])
        alphas[c] = a
        levels[:, j] = ses_levels(arr[:, j], a)
    pred = levels[rows["origin_idx"].to_numpy(), rows["component"].to_numpy()]
    return pred, alphas


def poisson_interval(mu: np.ndarray, coverage: float) -> tuple[np.ndarray, np.ndarray]:
    """Central Poisson interval around a mean forecast (assumes equidispersion; tends to under-cover)."""
    mu = np.clip(np.asarray(mu, dtype=float), 1e-9, None)
    tail = (1 - coverage) / 2
    return poisson.ppf(tail, mu).astype(float), poisson.ppf(1 - tail, mu).astype(float)


# --------------------------------------------------------------------------------------------------
# Estimators
# --------------------------------------------------------------------------------------------------

GBM_PARAMS = dict(
    learning_rate=0.05, max_iter=300, max_leaf_nodes=15, min_samples_leaf=20,
    l2_regularization=1.0, early_stopping=False,
)


def _glm_pipeline(n_components: int, alpha: float = 1e-3) -> Pipeline:
    pre = ColumnTransformer([
        ("comp", OneHotEncoder(categories=[list(range(n_components))], handle_unknown="ignore"), ["component"]),
        ("counts", make_pipeline(FunctionTransformer(np.log1p), StandardScaler()), COUNT_FEATURES),
        ("other", StandardScaler(), ["h", "woy_sin", "woy_cos"]),
    ])
    return Pipeline([("pre", pre), ("glm", PoissonRegressor(alpha=alpha, max_iter=1000))])


class HorizonModel(BaseEstimator, RegressorMixin):
    """Point model plus a prediction interval for one horizon regime (1-step or direct multi-horizon).

    kind='gbm': HistGradientBoostingRegressor with Poisson loss for the point forecast and two quantile
    models for the interval. kind='glm': Poisson GLM point forecast with a Poisson interval.
    """

    def __init__(self, kind: str = "gbm", n_components: int = 1, coverage: float = 0.90,
                 random_state: int = 42, fit_interval: bool = True):
        self.kind = kind
        self.n_components = n_components
        self.coverage = coverage
        self.random_state = random_state
        self.fit_interval = fit_interval

    def _gbm(self, **kw) -> HistGradientBoostingRegressor:
        return HistGradientBoostingRegressor(
            categorical_features=["component"], random_state=self.random_state, **GBM_PARAMS, **kw)

    def fit(self, X: pd.DataFrame, y: np.ndarray):
        X = X[FEATURES]
        tail = (1 - self.coverage) / 2
        if self.kind == "gbm":
            self.point_ = self._gbm(loss="poisson").fit(X, y)
            self.lower_ = self._gbm(loss="quantile", quantile=tail).fit(X, y) if self.fit_interval else None
            self.upper_ = self._gbm(loss="quantile", quantile=1 - tail).fit(X, y) if self.fit_interval else None
        elif self.kind == "glm":
            self.point_ = _glm_pipeline(self.n_components).fit(X, y)
            self.lower_ = self.upper_ = None
        else:
            raise ValueError(f"unknown kind {self.kind}")
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return np.clip(self.point_.predict(X[FEATURES]), 0, None)

    def predict_interval(self, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        point = self.predict(X)
        if self.kind == "gbm" and self.lower_ is not None:
            lo = np.clip(self.lower_.predict(X[FEATURES]), 0, None)
            hi = np.clip(self.upper_.predict(X[FEATURES]), 0, None)
            lo, hi = np.minimum(lo, point), np.maximum(hi, point)
        else:
            lo, hi = poisson_interval(point, self.coverage)
        return point, lo, hi


class ComplaintForecaster(BaseEstimator, RegressorMixin):
    """The registered model: a 1-step model for h == 1 and a direct multi-horizon model for h > 1.

    Input is the feature frame from `build_rows`; `components` maps the integer `component` code back to
    the canonical label and `train_end_week` is the last week used as a training target.
    """

    def __init__(self, one_step: HorizonModel | None = None, direct: HorizonModel | None = None,
                 components: Sequence[str] = (), train_end_week: str = "", coverage: float = 0.90):
        self.one_step = one_step
        self.direct = direct
        self.components = components
        self.train_end_week = train_end_week
        self.coverage = coverage

    def fit(self, X, y=None):  # fitted piecewise by the pipeline; present for the sklearn API
        return self

    def _route(self, X: pd.DataFrame) -> np.ndarray:
        return X["h"].to_numpy() == 1

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.predict_interval(X)[0]

    def predict_interval(self, X: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        n = len(X)
        out = [np.zeros(n), np.zeros(n), np.zeros(n)]
        mask = self._route(X)
        for model, m in ((self.one_step, mask), (self.direct, ~mask)):
            if m.any():
                for arr, vals in zip(out, model.predict_interval(X[m])):
                    arr[m] = vals
        return tuple(out)


# --------------------------------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------------------------------

def mae(y, f) -> float:
    y, f = np.asarray(y, float), np.asarray(f, float)
    return float(np.mean(np.abs(y - f))) if len(y) else float("nan")


def mape(y, f) -> float:
    """Mean absolute percentage error in percent over points with y > 0 (zero actuals are skipped because
    the ratio is undefined). NaN when every actual is zero."""
    y, f = np.asarray(y, float), np.asarray(f, float)
    m = y > 0
    return float(np.mean(np.abs(y[m] - f[m]) / y[m]) * 100) if m.any() else float("nan")


def smape(y, f) -> float:
    """Symmetric MAPE in percent (0 to 200); a point where both actual and forecast are 0 scores 0."""
    y, f = np.asarray(y, float), np.asarray(f, float)
    denom = np.abs(y) + np.abs(f)
    term = np.where(denom == 0, 0.0, 2 * np.abs(y - f) / np.where(denom == 0, 1, denom))
    return float(np.mean(term) * 100) if len(y) else float("nan")


def wape(y, f) -> float:
    """Weighted absolute percentage error: sum|error| / sum(actual), in percent."""
    y, f = np.asarray(y, float), np.asarray(f, float)
    s = y.sum()
    return float(np.abs(y - f).sum() / s * 100) if s > 0 else float("nan")


def seasonal_naive_scale(y_train, season: int = SEASON) -> float:
    """In-sample MAE of the seasonal naive method, the MASE denominator (Hyndman and Koehler, 2006)."""
    y = np.asarray(y_train, float)
    if len(y) <= season:
        return float("nan")
    return float(np.mean(np.abs(y[season:] - y[:-season])))


def mase(y, f, scale: float) -> float:
    return mae(y, f) / scale if scale and scale > 0 and np.isfinite(scale) else float("nan")


def coverage(y, lo, hi) -> float:
    y = np.asarray(y, float)
    return float(np.mean((y >= np.asarray(lo)) & (y <= np.asarray(hi)))) if len(y) else float("nan")


def score_predictions(pred: pd.DataFrame, scales: dict[str, float]) -> tuple[dict[str, float], pd.DataFrame]:
    """Overall and per-component metrics for a frame with component_name, week, y, forecast[, lower, upper].

    Overall: WAPE and MAE over all component-weeks; MAPE, sMAPE and MASE averaged across components
    weighted by actual volume; MAPE and WAPE of the total weekly volume (sum over components).
    """
    has_iv = {"lower", "upper"} <= set(pred.columns)
    rows = []
    for comp, g in pred.groupby("component_name", sort=True):
        r = {
            "component": comp, "volume": float(g["y"].sum()), "n_weeks": len(g),
            "zero_weeks": int((g["y"] == 0).sum()),
            "mae": mae(g["y"], g["forecast"]), "mape": mape(g["y"], g["forecast"]),
            "smape": smape(g["y"], g["forecast"]), "wape": wape(g["y"], g["forecast"]),
            "mase": mase(g["y"], g["forecast"], scales.get(comp, float("nan"))),
        }
        if has_iv:
            r["coverage"] = coverage(g["y"], g["lower"], g["upper"])
        rows.append(r)
    per = pd.DataFrame(rows)

    def wavg(col: str) -> float:
        m = per[col].notna() & (per["volume"] > 0)
        return float(np.average(per.loc[m, col], weights=per.loc[m, "volume"])) if m.any() else float("nan")

    tot = pred.groupby("week")[["y", "forecast"]].sum()
    overall = {
        "wape": wape(pred["y"], pred["forecast"]),
        "mae": mae(pred["y"], pred["forecast"]),
        "mape_vw": wavg("mape"),
        "smape_vw": wavg("smape"),
        "mase_vw": wavg("mase"),
        "total_mape": mape(tot["y"], tot["forecast"]),
        "total_wape": wape(tot["y"], tot["forecast"]),
    }
    if has_iv:
        overall["coverage"] = coverage(pred["y"], pred["lower"], pred["upper"])
    return overall, per


# --------------------------------------------------------------------------------------------------
# Spike rule
# --------------------------------------------------------------------------------------------------

def flag_spikes(actual, upper, min_count: float = 3) -> tuple[np.ndarray, np.ndarray]:
    """A spike is an actual strictly above the interval upper bound and at least `min_count` complaints.
    Returns (flag, ratio) where ratio = actual / max(upper, 1) so a near-zero bound does not explode it."""
    a, u = np.asarray(actual, float), np.asarray(upper, float)
    flag = (a > u) & (a >= min_count)
    ratio = a / np.maximum(u, 1.0)
    return flag, ratio
