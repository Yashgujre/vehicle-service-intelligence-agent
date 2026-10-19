"""Weekly complaint-volume forecasting per component, MLflow tracking and registry, spike detection (FR-7).

Usage (repo root, venv active):
    python -m pipelines.forecast train [--force]   # backtest all models, log to MLflow, register champion
    python -m pipelines.forecast detect            # champion forecasts + spike alerts -> forecasts, spike_alerts
    python -m pipelines.forecast all [--force]     # train then detect (what the weekly n8n job calls)

`train` is skipped when the current champion was trained on identical data and configuration (same
fingerprint), so `all` is idempotent and cheap to re-run. See docs/models/backtest-report.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "vsia-mpl"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sqlalchemy import delete, insert, select  # noqa: E402

from pipelines.features import (  # noqa: E402
    BASELINES,
    FEATURES,
    GBM_PARAMS,
    ComplaintForecaster,
    HorizonModel,
    baseline_forecast,
    build_rows,
    flag_spikes,
    poisson_interval,
    score_predictions,
    seasonal_naive_scale,
    ses_forecast,
    training_rows,
    weekly_counts,
)
from vsia.config import REPO_ROOT, env, settings  # noqa: E402
from vsia.db import complaints, engine, forecasts, recalls, spike_alerts  # noqa: E402

EXPERIMENT = "vsia-forecast"
REGISTERED_MODEL = "vsia-complaint-forecaster"
ALIAS = "champion"
PIPELINE_VERSION = "1.0"
SEED = 42
VALIDATION_FOLDS = 3          # rolling origins before the holdout, each `holdout_weeks` long
FUTURE_WEEKS = 4
RECENT_WEEKS = 4              # alerts in the last N complete weeks are "current"
MIN_ALERT_COUNT = 3           # ignore spikes of 1-2 complaints in sparse series
RECALL_WINDOW_DAYS = 28       # weak external check: recall report within +/- 4 weeks of an alert week
HEADLINE = "wape"             # component-level WAPE on 1-step-ahead holdout forecasts
CANDIDATES = ["naive", "snaive52", "ma4", "ma8", "ses", "glm_poisson", "gbm"]
SKLEARN_MODELS = {"glm_poisson": "glm", "gbm": "gbm"}
PLOT_DIR = REPO_ROOT / "docs" / "models" / "forecast-plots"


def log(msg: str) -> None:
    print(f"[forecast] {msg}", flush=True)


# --------------------------------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------------------------------

def forecast_settings() -> dict:
    s = settings()["forecast"]
    return {
        "freq": s.get("freq", "W-MON"),
        "holdout_weeks": int(s.get("holdout_weeks", 12)),
        "min_weekly_total": int(s.get("min_weekly_total", 30)),
        "spike_interval": float(s.get("spike_interval", 0.90)),
    }


def load_panel(cfg: dict) -> pd.DataFrame:
    with engine().connect() as conn:
        df = pd.read_sql(select(complaints.c.date_filed, complaints.c.component_primary), conn)
    return weekly_counts(df, freq=cfg["freq"], min_total=cfg["min_weekly_total"])


def fingerprint(Y: pd.DataFrame, cfg: dict) -> str:
    h = hashlib.sha256()
    h.update(Y.to_csv().encode())
    h.update(json.dumps({**cfg, "pipeline": PIPELINE_VERSION, "seed": SEED, "gbm": GBM_PARAMS,
                         "candidates": CANDIDATES, "folds": VALIDATION_FOLDS}, sort_keys=True).encode())
    return h.hexdigest()[:16]


# --------------------------------------------------------------------------------------------------
# Backtest
# --------------------------------------------------------------------------------------------------

def fit_horizon_model(name: str, Y: pd.DataFrame, end_idx: int, horizons, coverage: float,
                      fit_interval: bool) -> HorizonModel:
    tr = training_rows(Y, end_idx, horizons)
    return HorizonModel(kind=SKLEARN_MODELS[name], n_components=Y.shape[1], coverage=coverage,
                        random_state=SEED, fit_interval=fit_interval).fit(tr, tr["y"].to_numpy())


def predict_fold(name: str, Y: pd.DataFrame, start: int, H: int, coverage: float, final: bool):
    """1-step-ahead forecasts for targets start..start+H-1 (origin = target - 1, actuals known up to the
    origin, parameters fixed at the fold start) and direct forecasts from origin start-1 for h = 1..H."""
    one = build_rows(Y, range(start - 1, start + H - 1), [1])
    direct = build_rows(Y, [start - 1], list(range(1, H + 1)))
    model = None
    if name in BASELINES:
        preds = [baseline_forecast(r, name) for r in (one, direct)]
        bands = [poisson_interval(p, coverage) for p in preds]
    elif name == "ses":
        preds = [ses_forecast(Y, start, r)[0] for r in (one, direct)]
        bands = [poisson_interval(p, coverage) for p in preds]
    else:
        m1 = fit_horizon_model(name, Y, start, [1], coverage, fit_interval=final)
        mh = fit_horizon_model(name, Y, start, list(range(1, H + 1)), coverage, fit_interval=final)
        res = [m.predict_interval(r) for m, r in ((m1, one), (mh, direct))]
        preds = [r[0] for r in res]
        bands = [(r[1], r[2]) for r in res]
        if final:
            model = ComplaintForecaster(one_step=m1, direct=mh, components=list(Y.columns),
                                        train_end_week=str(Y.index[start - 1].date()), coverage=coverage)
    out = []
    for mode, rows, p, (lo, hi) in zip(("1step", "direct"), (one, direct), preds, bands):
        out.append(pd.DataFrame({
            "mode": mode, "component_name": rows["component_name"], "week": rows["week"], "h": rows["h"],
            "y": rows["y"], "forecast": p, "lower": lo, "upper": hi,
        }))
    return pd.concat(out, ignore_index=True), model


def backtest(Y: pd.DataFrame, cfg: dict) -> dict:
    H = cfg["holdout_weeks"]
    T = len(Y)
    holdout_start = T - H
    starts = [holdout_start - H * k for k in range(VALIDATION_FOLDS, 0, -1)] + [holdout_start]
    results = {}
    for name in CANDIDATES:
        t0 = time.time()
        folds, model = [], None
        for i, s in enumerate(starts):
            final = s == holdout_start
            pred, m = predict_fold(name, Y, s, H, cfg["spike_interval"], final)
            scales = {c: seasonal_naive_scale(Y[c].to_numpy()[:s]) for c in Y.columns}
            fold = {"fold": i, "start": str(Y.index[s].date()), "holdout": final, "pred": pred}
            for mode in ("1step", "direct"):
                fold[mode] = score_predictions(pred[pred["mode"] == mode], scales)
            folds.append(fold)
            model = m if final else model
        results[name] = {"folds": folds, "model": model, "seconds": time.time() - t0}
        hold = folds[-1]["1step"][0]
        val = np.mean([f["1step"][0][HEADLINE] for f in folds[:-1]])
        log(f"{name:12s} val WAPE {val:6.2f}  holdout 1-step WAPE {hold['wape']:6.2f}  "
            f"MASE {hold['mase_vw']:.3f}  total MAPE {hold['total_mape']:6.2f}  ({time.time() - t0:.1f}s)")
    return {"results": results, "starts": starts, "holdout_start": holdout_start}


# --------------------------------------------------------------------------------------------------
# MLflow
# --------------------------------------------------------------------------------------------------

def mlflow_setup():
    import mlflow
    import mlflow.sklearn  # noqa: F401

    mlflow.set_tracking_uri(env().mlflow_tracking_uri)
    exp = mlflow.get_experiment_by_name(EXPERIMENT)
    if exp is None:
        root = Path(env().mlflow_artifact_root)
        root.mkdir(parents=True, exist_ok=True)
        mlflow.create_experiment(EXPERIMENT, artifact_location=root.resolve().as_uri())
    mlflow.set_experiment(EXPERIMENT)
    return mlflow


def current_champion(mlflow):
    from mlflow.exceptions import MlflowException

    client = mlflow.MlflowClient()
    try:
        return client.get_model_version_by_alias(REGISTERED_MODEL, ALIAS)
    except MlflowException:
        return None


def metric_key(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in s).strip("_")


def summarize(bt: dict) -> pd.DataFrame:
    rows = []
    snaive_hold = bt["results"]["snaive52"]["folds"][-1]
    for name, r in bt["results"].items():
        folds = r["folds"]
        hold1, holdd = folds[-1]["1step"][0], folds[-1]["direct"][0]
        rows.append({
            "model": name,
            "val_wape_1step": np.mean([f["1step"][0]["wape"] for f in folds[:-1]]),
            "val_mase_1step": np.mean([f["1step"][0]["mase_vw"] for f in folds[:-1]]),
            "hold_wape_1step": hold1["wape"], "hold_mae_1step": hold1["mae"],
            "hold_mase_1step": hold1["mase_vw"], "hold_smape_1step": hold1["smape_vw"],
            "hold_mape_vw_1step": hold1["mape_vw"], "hold_total_mape_1step": hold1["total_mape"],
            "hold_coverage_1step": hold1.get("coverage", np.nan),
            "rel_wape_vs_snaive_1step": hold1["wape"] / snaive_hold["1step"][0]["wape"],
            "hold_wape_direct": holdd["wape"], "hold_mase_direct": holdd["mase_vw"],
            "hold_total_mape_direct": holdd["total_mape"],
            "rel_wape_vs_snaive_direct": holdd["wape"] / snaive_hold["direct"][0]["wape"],
        })
    return pd.DataFrame(rows)


def log_runs(mlflow, Y: pd.DataFrame, cfg: dict, bt: dict, fp: str, summary: pd.DataFrame,
             plots: list[Path]) -> dict:
    from mlflow.models import infer_signature

    run_ids = {}
    common = {"freq": cfg["freq"], "holdout_weeks": cfg["holdout_weeks"], "min_weekly_total": cfg["min_weekly_total"],
              "interval": cfg["spike_interval"], "n_weeks": len(Y), "n_components": Y.shape[1],
              "first_week": str(Y.index[0].date()), "last_week": str(Y.index[-1].date()),
              "holdout_start": str(Y.index[bt["holdout_start"]].date()), "validation_folds": VALIDATION_FOLDS,
              "pooled_components": ",".join(Y.attrs.get("pooled", [])) or "none", "seed": SEED,
              "headline_metric": "holdout 1-step component WAPE"}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with mlflow.start_run(run_name=f"train-{stamp}") as parent:
        mlflow.set_tags({"data_fingerprint": fp, "pipeline_version": PIPELINE_VERSION, "kind": "train"})
        mlflow.log_params(common)
        with tempfile.TemporaryDirectory() as tmp:
            Y.to_csv(Path(tmp) / "weekly_counts.csv")
            summary.to_csv(Path(tmp) / "summary.csv", index=False)
            mlflow.log_artifacts(tmp)
        for p in plots:
            mlflow.log_artifact(str(p), artifact_path="plots")
        for name, r in bt["results"].items():
            with mlflow.start_run(run_name=name, nested=True) as run:
                run_ids[name] = run.info.run_id
                mlflow.set_tags({"data_fingerprint": fp, "model_family": name, "kind": "candidate"})
                params = {**common, "model": name}
                if name in SKLEARN_MODELS:
                    params.update({"features": ",".join(FEATURES), "estimator": SKLEARN_MODELS[name]})
                    if name == "gbm":
                        params.update({f"gbm_{k}": v for k, v in GBM_PARAMS.items()})
                        params["gbm_point_loss"] = "poisson"
                        params["interval_method"] = "quantile gbm"
                    else:
                        params["interval_method"] = "poisson"
                else:
                    params["interval_method"] = "poisson"
                mlflow.log_params(params)
                row = summary.set_index("model").loc[name]
                mlflow.log_metrics({k: float(v) for k, v in row.items() if pd.notna(v)})
                hold = r["folds"][-1]
                for mode in ("1step", "direct"):
                    overall, per = hold[mode]
                    mlflow.log_metrics({f"holdout_{mode}_{k}": float(v) for k, v in overall.items() if pd.notna(v)})
                    for _, pr in per.iterrows():
                        for k in ("wape", "mae", "mase", "smape", "mape"):
                            if pd.notna(pr[k]):
                                mlflow.log_metric(f"holdout_{mode}_{k}__{metric_key(pr['component'])}", float(pr[k]))
                with tempfile.TemporaryDirectory() as tmp:
                    allp = pd.concat([f["pred"].assign(fold=f["fold"], fold_start=f["start"]) for f in r["folds"]])
                    allp.to_csv(Path(tmp) / "forecasts.csv", index=False)
                    hold["1step"][1].to_csv(Path(tmp) / "per_component_1step.csv", index=False)
                    hold["direct"][1].to_csv(Path(tmp) / "per_component_direct.csv", index=False)
                    (Path(tmp) / "features.json").write_text(json.dumps(FEATURES if name in SKLEARN_MODELS
                                                                        else [BASELINES.get(name, "level")]))
                    mlflow.log_artifacts(tmp)
                if r["model"] is not None:
                    ex = build_rows(Y, [bt["holdout_start"] - 1], [1])[FEATURES].head(5)
                    sig = infer_signature(ex, r["model"].predict(ex))
                    info = mlflow.sklearn.log_model(
                        sk_model=r["model"], name="model", signature=sig, input_example=ex,
                        code_paths=[str(REPO_ROOT / "pipelines")],
                        # skops (the MLflow 3 default) rejects the custom wrapper classes and
                        # HistGradientBoosting's TreePredictor. cloudpickle executes code on load, so only
                        # models written by this pipeline to this registry may be loaded (ADR-0055).
                        serialization_format=mlflow.sklearn.SERIALIZATION_FORMAT_CLOUDPICKLE,
                        pip_requirements=["scikit-learn==" + __import__("sklearn").__version__,
                                          "pandas", "numpy", "scipy"],
                    )
                    r["model_uri"] = info.model_uri
    run_ids["parent"] = parent.info.run_id
    return run_ids


def register_champion(mlflow, bt: dict, summary: pd.DataFrame, run_ids: dict, fp: str, Y: pd.DataFrame) -> dict:
    cand = summary[summary["model"].isin(SKLEARN_MODELS)].sort_values("val_wape_1step")
    name = cand.iloc[0]["model"]
    row = summary.set_index("model").loc[name]
    mv = mlflow.register_model(bt["results"][name]["model_uri"], REGISTERED_MODEL)
    client = mlflow.MlflowClient()
    client.set_registered_model_alias(REGISTERED_MODEL, ALIAS, mv.version)
    tags = {
        "data_fingerprint": fp, "model_family": name, "run_id": run_ids[name],
        "train_end_week": bt["results"][name]["model"].train_end_week,
        "holdout_wape_1step": f"{row['hold_wape_1step']:.3f}",
        "rel_wape_vs_snaive_1step": f"{row['rel_wape_vs_snaive_1step']:.3f}",
        "beats_seasonal_naive_1step": str(bool(row["rel_wape_vs_snaive_1step"] < 1)),
        "validation_status": "backtested",
    }
    for k, v in tags.items():
        client.set_model_version_tag(REGISTERED_MODEL, mv.version, k, v)
    client.update_model_version(
        REGISTERED_MODEL, mv.version,
        description=(f"{name}: lowest mean validation WAPE (1-step) over {VALIDATION_FOLDS} rolling origins. "
                     f"Holdout 1-step WAPE {row['hold_wape_1step']:.2f}% vs seasonal naive "
                     f"ratio {row['rel_wape_vs_snaive_1step']:.3f}. Data {Y.index[0].date()} to "
                     f"{Y.index[-1].date()}."),
    )
    return {"model": name, "version": mv.version, "run_id": run_ids[name]}


# --------------------------------------------------------------------------------------------------
# Plots
# --------------------------------------------------------------------------------------------------

def make_plots(Y: pd.DataFrame, bt: dict, champion: str) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    hs = Y.index[bt["holdout_start"]]
    champ = bt["results"][champion]["folds"][-1]["pred"]
    champ = champ[champ["mode"] == "1step"]
    snv = bt["results"]["snaive52"]["folds"][-1]["pred"]
    snv = snv[snv["mode"] == "1step"]
    paths = []

    total = Y.sum(axis=1)
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(total.index, total.values, color="#333", lw=1, label="Actual (all components)")
    ax.plot(total.rolling(13).mean(), color="#1f77b4", lw=1.5, label="13-week moving average")
    ct = champ.groupby("week")[["forecast", "lower", "upper"]].sum()
    ax.plot(ct.index, ct["forecast"], color="#d62728", lw=1.5, label=f"{champion} 1-step forecast (sum)")
    st = snv.groupby("week")["forecast"].sum()
    ax.plot(st.index, st.values, color="#2ca02c", lw=1, ls="--", label="Seasonal naive (sum)")
    ax.axvspan(hs, Y.index[-1], color="#ddd", alpha=0.6, label="Holdout")
    ax.set_title("Weekly complaint volume, all components (Monday-start weeks)")
    ax.set_ylabel("Complaints per week")
    ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout()
    p = PLOT_DIR / "overall_weekly_volume.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    paths.append(p)

    top = Y.sum().sort_values(ascending=False).index[:6]
    fig, axes = plt.subplots(3, 2, figsize=(12, 9), sharex=True)
    ctx_start = bt["holdout_start"] - 40
    for ax, comp in zip(axes.ravel(), top):
        hist = Y[comp].iloc[ctx_start:]
        g = champ[champ["component_name"] == comp]
        s = snv[snv["component_name"] == comp]
        ax.plot(hist.index, hist.values, color="#333", lw=1, marker=".", ms=3, label="Actual")
        ax.fill_between(g["week"], g["lower"], g["upper"], color="#d62728", alpha=0.18,
                        label=f"{int(bt['interval'] * 100)}% interval")
        ax.plot(g["week"], g["forecast"], color="#d62728", lw=1.5, label=f"{champion} 1-step")
        ax.plot(s["week"], s["forecast"], color="#2ca02c", lw=1, ls="--", label="Seasonal naive")
        flagged = g[(g["y"] > g["upper"]) & (g["y"] >= MIN_ALERT_COUNT)]
        ax.scatter(flagged["week"], flagged["y"], color="#ff7f0e", zorder=5, s=30, label="Spike flag")
        ax.axvline(hs, color="#999", ls=":")
        ax.set_title(comp, fontsize=10)
        ax.tick_params(labelsize=8)
    axes[0, 0].legend(fontsize=7, loc="upper left")
    fig.suptitle("Top 6 components: holdout actual vs 1-step forecast with prediction interval", fontsize=11)
    fig.autofmt_xdate()
    fig.tight_layout()
    p = PLOT_DIR / "top6_components_holdout.png"
    fig.savefig(p, dpi=120)
    plt.close(fig)
    paths.append(p)
    return paths


# --------------------------------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------------------------------

def cmd_train(force: bool = False) -> dict | None:
    t0 = time.time()
    np.random.seed(SEED)
    cfg = forecast_settings()
    Y = load_panel(cfg)
    fp = fingerprint(Y, cfg)
    log(f"panel: {len(Y)} weeks x {Y.shape[1]} components, {Y.index[0].date()} to {Y.index[-1].date()}, "
        f"pooled into OTHER: {Y.attrs.get('pooled')}, fingerprint {fp}")
    mlflow = mlflow_setup()
    champ = current_champion(mlflow)
    if champ is not None and champ.tags.get("data_fingerprint") == fp and not force:
        log(f"champion v{champ.version} already trained on this data and config; skipping train (use --force)")
        return None
    bt = backtest(Y, cfg)
    bt["interval"] = cfg["spike_interval"]
    summary = summarize(bt)
    best = summary[summary["model"].isin(SKLEARN_MODELS)].sort_values("val_wape_1step").iloc[0]["model"]
    plots = make_plots(Y, bt, best)
    run_ids = log_runs(mlflow, Y, cfg, bt, fp, summary, plots)
    champion = register_champion(mlflow, bt, summary, run_ids, fp, Y)
    pd.set_option("display.width", 200)
    print(summary.round(3).to_string(index=False))
    log(f"run ids: {json.dumps(run_ids)}")
    log(f"champion: {champion['model']} -> {REGISTERED_MODEL} v{champion['version']} @{ALIAS} "
        f"(run {champion['run_id']}); train took {time.time() - t0:.1f}s")
    return {"summary": summary, "run_ids": run_ids, "champion": champion}


def recall_dates() -> pd.DataFrame:
    with engine().connect() as conn:
        r = pd.read_sql(select(recalls.c.campaign_number, recalls.c.report_date, recalls.c.component_primary), conn)
    r = r.dropna(subset=["report_date"]).drop_duplicates(["campaign_number", "component_primary"])
    r["report_date"] = pd.to_datetime(r["report_date"])
    return r


def near_recall(frame: pd.DataFrame, rec: pd.DataFrame) -> list[str]:
    out = []
    win = pd.Timedelta(days=RECALL_WINDOW_DAYS)
    for comp, week in zip(frame["component"], frame["week"]):
        m = rec[(rec["component_primary"] == comp) & (rec["report_date"] >= week - win)
                & (rec["report_date"] <= week + pd.Timedelta(days=6) + win)]
        out.append(",".join(sorted(m["campaign_number"].unique())))
    return out


def cmd_detect() -> dict:
    t0 = time.time()
    cfg = forecast_settings()
    mlflow = mlflow_setup()
    champ = current_champion(mlflow)
    if champ is None:
        raise SystemExit(f"no {REGISTERED_MODEL}@{ALIAS}; run `python -m pipelines.forecast train` first")
    model: ComplaintForecaster = mlflow.sklearn.load_model(f"models:/{REGISTERED_MODEL}@{ALIAS}")
    run_id = champ.run_id or champ.tags.get("run_id")
    family = champ.tags.get("model_family", "champion")
    Y = load_panel(cfg)
    if list(Y.columns) != list(model.components):
        raise SystemExit(f"component set changed since training ({list(model.components)} vs "
                         f"{list(Y.columns)}); retrain with `train --force`")
    train_end = pd.Timestamp(model.train_end_week)
    T = len(Y)
    first_oos = int(np.searchsorted(Y.index, train_end, side="right"))
    if first_oos >= T:
        raise SystemExit("no complete weeks after the champion's training window; nothing to evaluate")

    hist = build_rows(Y, range(first_oos - 1, T - 1), [1])
    fut = build_rows(Y, [T - 1], list(range(1, FUTURE_WEEKS + 1)))
    frames = []
    for rows, is_hold in ((hist, True), (fut, False)):
        p, lo, hi = model.predict_interval(rows)
        frames.append(pd.DataFrame({"component": rows["component_name"], "week": rows["week"], "actual": rows["y"],
                                    "forecast": p, "lower": lo, "upper": hi, "is_holdout": is_hold}))
    fc = pd.concat(frames, ignore_index=True)
    h = fc[fc["is_holdout"]].copy()
    flag, ratio = flag_spikes(h["actual"], h["upper"], MIN_ALERT_COUNT)
    h["ratio"] = ratio
    alerts = h[flag].copy()
    rec = recall_dates()
    alerts["recalls_near"] = near_recall(alerts, rec)
    base = near_recall(h, rec)
    base_rate = float(np.mean([bool(x) for x in base])) if len(base) else float("nan")
    recent_from = Y.index[-RECENT_WEEKS]
    alerts["current"] = alerts["week"] >= recent_from

    weeks_written = sorted({w.date() for w in fc["week"]})
    weeks_eval = sorted({w.date() for w in h["week"]})
    with engine().begin() as conn:
        conn.execute(delete(forecasts).where(forecasts.c.week.in_(weeks_written)))
        conn.execute(delete(spike_alerts).where(spike_alerts.c.week.in_(weeks_eval)))
        conn.execute(insert(forecasts), [
            {"run_id": run_id, "component": r.component, "week": r.week.date(),
             "actual": None if pd.isna(r.actual) else float(r.actual), "forecast": float(r.forecast),
             "lower": float(r.lower), "upper": float(r.upper), "model_name": f"{family}@v{champ.version}",
             "is_holdout": bool(r.is_holdout)} for r in fc.itertuples()])
        if len(alerts):
            conn.execute(insert(spike_alerts), [
                {"run_id": run_id, "component": r.component, "week": r.week.date(), "actual": float(r.actual),
                 "upper": float(r.upper), "ratio": float(r.ratio)} for r in alerts.itertuples()])

    pd.set_option("display.width", 200)
    log(f"champion {family} v{champ.version} (run {run_id}), trained through {train_end.date()}")
    log(f"out-of-sample weeks evaluated: {len(weeks_eval)} ({weeks_eval[0]} to {weeks_eval[-1]}), "
        f"component-weeks {len(h)}, interval coverage {np.mean((h.actual >= h.lower) & (h.actual <= h.upper)):.3f}")
    log(f"alerts fired: {len(alerts)} (current, last {RECENT_WEEKS} weeks: {int(alerts['current'].sum())}); "
        f"recall within +/-{RECALL_WINDOW_DAYS}d: {int((alerts['recalls_near'] != '').sum())} of {len(alerts)} "
        f"alerts vs base rate {base_rate:.3f} of all evaluated component-weeks")
    if len(alerts):
        show = alerts.assign(week=alerts["week"].dt.date).round(2)
        print(show[["component", "week", "actual", "forecast", "upper", "ratio", "current", "recalls_near"]]
              .to_string(index=False))
    log(f"wrote {len(fc)} forecast rows ({FUTURE_WEEKS} future weeks) and {len(alerts)} alert rows; "
        f"detect took {time.time() - t0:.1f}s")
    return {"alerts": alerts, "forecasts": fc, "base_rate": base_rate, "run_id": run_id}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pipelines.forecast", description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["train", "detect", "all"])
    ap.add_argument("--force", action="store_true", help="retrain even if the data fingerprint is unchanged")
    args = ap.parse_args(argv)
    t0 = time.time()
    if args.command in ("train", "all"):
        cmd_train(force=args.force)
    if args.command in ("detect", "all"):
        cmd_detect()
    log(f"{args.command} finished in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
