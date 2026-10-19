"""Read-only data access for the dashboard (FR-8).

Every panel reads through this module. It runs against one of three sources:

  live   the project database from vsia.db.engine() (SQLite locally, Postgres via DATABASE_URL)
  demo   parquet snapshots in app/demo_data/, written by scripts/export_demo_snapshot.py; used when
         VSIA_DEMO_SNAPSHOT=1 or when no database is reachable (Streamlit Community Cloud)
  empty  neither is available; every query returns an empty frame and pages show "no data yet"

Queries use SQLAlchemy Core so they stay portable between SQLite and Postgres. Each loader selects a
narrow column set and aggregation happens in pandas, so the same code serves both live and demo mode.
The only write path is submit_review(), which delegates to vsia.review.decide() and refuses to run in
read-only mode (VSIA_READONLY=1, or any demo source).

Complaint text and free-text model output pass through vsia.guardrails.redact() before they leave this
module. complaints.component_primary is NHTSA's coded label; the dashboard shows it as the reference
component for volume charts, never as model input.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from sqlalchemy import JSON, Date, DateTime, func, select

from vsia import config as vconfig
from vsia import db
from vsia.guardrails import redact

DEMO_DIR = APP_DIR / "demo_data"
CACHE_TTL_S = 300
RECENT_ALERT_WEEKS = 4  # same window the forecast pipeline uses for "current" alerts
NHTSA_RECALL_URL = "https://www.nhtsa.gov/recalls?nhtsaId={campaign}"

# Command that fills each source table; used in "no data yet" messages.
COMMANDS = {
    "complaints": "vsia ingest",
    "ingestion_runs": "vsia ingest",
    "triage_records": "vsia triage --limit 50",
    "review_queue": "vsia triage --limit 50",
    "forecasts": "python -m pipelines.forecast all",
    "spike_alerts": "python -m pipelines.forecast all",
    "eval_runs": "python -m eval.run_eval all --provider ollama",
    "llm_calls": "vsia triage --limit 50 --provider <ollama|anthropic|openai>",
    "routing": "python -m eval.run_eval calibrate --provider <provider>",
    "snapshot": "python scripts/export_demo_snapshot.py",
}

COMPLAINT_COLS = ("odi_number", "make", "model", "model_year", "date_filed", "component_primary",
                  "crash", "fire", "injuries", "deaths")
TRIAGE_LIST_COLS = ("id", "odi_number", "run_id", "component", "severity", "recall_campaigns", "confidence",
                    "route", "provider", "model", "prompt_version", "latency_ms", "cost_usd", "created_at")
TRIAGE_DETAIL_COLS = TRIAGE_LIST_COLS + ("schema_version", "output", "confidence_signals", "cited_sources")
RECALL_COLS = ("campaign_number", "make", "model", "model_year", "report_date", "component_primary",
               "component_raw", "summary", "consequence", "remedy")
LLM_SUMMARY_COLS = ["provider", "model", "purpose", "calls", "errors", "error_rate", "total_cost_usd",
                    "cost_per_1k_calls_usd", "p50_latency_ms", "p95_latency_ms", "avg_input_tokens",
                    "avg_output_tokens"]
PENDING_COLS = ["queue_id", "odi_number", "reason", "created_at", "triage_record_id", "component", "severity",
                "recall_campaigns", "confidence", "provider", "make", "model", "model_year", "summary"]

# Snapshot-only tables (not in vsia.db.metadata).
SNAPSHOT_EXTRA = ("complaint_texts", "llm_cost_summary")


# --------------------------------------------------------------------------------------------------
# Source resolution
# --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Source:
    mode: str  # live | demo | empty
    reason: str
    readonly: bool
    engine: Any = field(default=None, compare=False, repr=False)
    demo_dir: Path = DEMO_DIR

    @property
    def key(self) -> str:
        url = self.engine.url.render_as_string(hide_password=True) if self.engine is not None else ""
        return f"{self.mode}|{self.demo_dir}|{url}"


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def demo_available(demo_dir: Path = DEMO_DIR) -> bool:
    return (demo_dir / "complaints.parquet").exists()


def _demo(reason: str, demo_dir: Path = DEMO_DIR) -> Source:
    if demo_available(demo_dir):
        return Source("demo", f"demo snapshot ({reason})", readonly=True, demo_dir=demo_dir)
    return Source("empty", f"{reason}; no demo snapshot in app/demo_data", readonly=True, demo_dir=demo_dir)


def resolve_source(demo_dir: Path = DEMO_DIR) -> Source:
    """Pick live, demo or empty. Never creates a SQLite file that does not exist yet."""
    readonly = _flag("VSIA_READONLY")
    if _flag("VSIA_DEMO_SNAPSHOT"):
        return _demo("VSIA_DEMO_SNAPSHOT=1", demo_dir)
    url = vconfig.env().database_url
    if url.startswith("sqlite"):
        path = url.split("///", 1)[-1]
        if path and path != ":memory:" and not Path(path).exists():
            return _demo("no database file", demo_dir)
    try:
        eng = db.engine()
        with eng.connect() as conn:
            n = conn.execute(select(func.count()).select_from(db.complaints)).scalar_one()
    except Exception as e:  # noqa: BLE001
        return _demo(f"database not reachable: {type(e).__name__}", demo_dir)
    if n == 0 and demo_available(demo_dir):
        return _demo("database has no complaints", demo_dir)
    return Source("live", f"live database ({eng.url.get_backend_name()})", readonly=readonly, engine=eng,
                  demo_dir=demo_dir)


# --------------------------------------------------------------------------------------------------
# Low-level loading
# --------------------------------------------------------------------------------------------------

def _json_cols(table_name: str) -> set[str]:
    t = db.metadata.tables.get(table_name)
    return {c.name for c in t.columns if isinstance(c.type, JSON)} if t is not None else set()


def _time_cols(table_name: str) -> set[str]:
    t = db.metadata.tables.get(table_name)
    return {c.name for c in t.columns if isinstance(c.type, (Date, DateTime))} if t is not None else set()


def _decode_json(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def read_snapshot(demo_dir: Path, name: str) -> pd.DataFrame:
    p = demo_dir / f"{name}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    p = demo_dir / f"{name}.csv"
    if p.exists():
        return pd.read_csv(p)
    return pd.DataFrame()


def _normalize(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    for c in _json_cols(table_name) & set(df.columns):
        df[c] = df[c].map(_decode_json)
    for c in _time_cols(table_name) & set(df.columns):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def load_frame(src: Source, table_name: str, columns: tuple[str, ...] | None = None,
               ids: list[int] | None = None, id_col: str = "id") -> pd.DataFrame:
    """Rows of one table as a DataFrame with exactly `columns`. Empty frame when there is no data."""
    table = db.metadata.tables[table_name]
    cols = list(columns) if columns else [c.name for c in table.columns]
    if src.mode == "live":
        stmt = select(*[table.c[c] for c in cols])
        if ids is not None:
            if not ids:
                return pd.DataFrame(columns=cols)
            stmt = stmt.where(table.c[id_col].in_([int(i) for i in ids]))
        with src.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        df = pd.DataFrame([dict(r) for r in rows], columns=cols)
    elif src.mode == "demo":
        df = read_snapshot(src.demo_dir, table_name)
        for c in cols:
            if c not in df.columns:
                df[c] = None
        df = df[cols].copy()
        if ids is not None:
            df = df[df[id_col].isin([int(i) for i in ids])]
    else:
        df = pd.DataFrame(columns=cols)
    return _normalize(df.reset_index(drop=True), table_name)


def redact_obj(obj: Any) -> Any:
    """Redact every string inside a JSON-like value (model output can quote complaint text)."""
    if isinstance(obj, str):
        return redact(obj).text
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v) for v in obj]
    return obj


def _as_list(v: Any) -> list:
    v = _decode_json(v)
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return []
    if isinstance(v, (list, tuple)):
        return list(v)
    if hasattr(v, "tolist"):
        return list(v.tolist())
    return [v]


# --------------------------------------------------------------------------------------------------
# Complaints and volume
# --------------------------------------------------------------------------------------------------

def complaints(src: Source) -> pd.DataFrame:
    df = load_frame(src, "complaints", COMPLAINT_COLS)
    df["component_primary"] = df["component_primary"].fillna("OTHER")
    return df


def filter_complaints(df: pd.DataFrame, makes: list[str] | None = None, model_years: list[int] | None = None,
                      date_from: date | None = None, date_to: date | None = None) -> pd.DataFrame:
    m = pd.Series(True, index=df.index)
    if makes:
        m &= df["make"].isin(makes)
    if model_years:
        m &= df["model_year"].isin(model_years)
    if date_from is not None:
        m &= df["date_filed"] >= pd.Timestamp(date_from)
    if date_to is not None:
        m &= df["date_filed"] <= pd.Timestamp(date_to)
    return df[m]


def week_start(s: pd.Series) -> pd.Series:
    """Monday of the week, matching the forecast pipeline's W-MON week start."""
    d = pd.to_datetime(s).dt.normalize()
    return d - pd.to_timedelta(d.dt.weekday, unit="D")


def weekly_counts(df: pd.DataFrame, by: str | None = None, components: list[str] | None = None,
                  drop_partial: bool = True) -> pd.DataFrame:
    """Complaints per week (week starting Monday), zero-filled. Long format: week, [by], count.
    The trailing week is dropped when it is not complete in the data, as in the forecast pipeline."""
    cols = ["week", by, "count"] if by else ["week", "count"]
    d = df.dropna(subset=["date_filed"])
    if d.empty:
        return pd.DataFrame(columns=cols)
    all_weeks = week_start(d["date_filed"])
    weeks = pd.date_range(all_weeks.min(), all_weeks.max(), freq="7D")
    if drop_partial and weeks[-1] + pd.Timedelta(days=6) > pd.to_datetime(d["date_filed"]).max().normalize():
        weeks = weeks[:-1]
    if components and by:
        d = d[d[by].isin(components)]
    if d.empty or not len(weeks):
        return pd.DataFrame(columns=cols)
    wk = week_start(d["date_filed"])
    if by:
        wide = (pd.DataFrame({"week": wk, by: d[by].to_numpy()}).groupby(["week", by]).size()
                .unstack(fill_value=0).reindex(weeks, fill_value=0))
        wide.index.name = "week"
        out = wide.reset_index().melt(id_vars="week", var_name=by, value_name="count")
    else:
        out = wk.value_counts().reindex(weeks, fill_value=0).rename_axis("week").reset_index(name="count")
    out["count"] = out["count"].astype(int)
    return out[cols].sort_values(cols[:-1]).reset_index(drop=True)


def top_components(df: pd.DataFrame, n: int = 12) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["component", "count"])
    vc = df["component_primary"].value_counts().head(n)
    return vc.rename_axis("component").reset_index(name="count")


def latest_ingestion(src: Source) -> dict | None:
    df = load_frame(src, "ingestion_runs", ("id", "kind", "started_at", "finished_at", "rows_fetched",
                                             "rows_inserted", "rows_skipped_duplicate", "ok", "error"))
    if df.empty:
        return None
    row = df.sort_values(["finished_at", "id"], na_position="first").iloc[-1]
    return {k: (None if pd.isna(v) else v) if not isinstance(v, (list, dict)) else v for k, v in row.items()}


def ingestion_runs(src: Source) -> pd.DataFrame:
    df = load_frame(src, "ingestion_runs", ("id", "kind", "started_at", "finished_at", "rows_fetched",
                                             "rows_inserted", "rows_skipped_duplicate", "rows_filtered", "ok"))
    return df.sort_values("id", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------------------------------
# Triage and review
# --------------------------------------------------------------------------------------------------

def triage_table(src: Source, latest_only: bool = True) -> pd.DataFrame:
    """Triage records joined to complaint vehicle fields. latest_only keeps the newest record per complaint."""
    tr = load_frame(src, "triage_records", TRIAGE_LIST_COLS)
    if tr.empty:
        return pd.DataFrame(columns=[*TRIAGE_LIST_COLS, "make", "vehicle_model", "model_year", "date_filed"])
    tr = tr.sort_values(["created_at", "id"])
    if latest_only:
        tr = tr.drop_duplicates("odi_number", keep="last")
    comp = load_frame(src, "complaints", ("odi_number", "make", "model", "model_year", "date_filed"))
    comp = comp.rename(columns={"model": "vehicle_model"})
    out = tr.merge(comp, on="odi_number", how="left")
    out["recall_campaigns"] = out["recall_campaigns"].map(_as_list)
    return out.sort_values(["created_at", "id"], ascending=False).reset_index(drop=True)


def triage_summary(src: Source) -> dict:
    """Counts over the latest record per complaint; cost over every triage record (each one was paid for)."""
    all_tr = load_frame(src, "triage_records", ("id", "odi_number", "route", "cost_usd", "created_at"))
    if all_tr.empty:
        return {"triaged": 0, "triage_runs": 0, "auto_routed_pct": None, "triage_cost_usd": 0.0,
                "cost_per_1000_triaged_usd": None}
    latest = all_tr.sort_values(["created_at", "id"]).drop_duplicates("odi_number", keep="last")
    cost = float(pd.to_numeric(all_tr["cost_usd"], errors="coerce").fillna(0).sum())
    return {
        "triaged": len(latest),
        "triage_runs": len(all_tr),
        "auto_routed_pct": float((latest["route"] == "auto").mean() * 100),
        "triage_cost_usd": cost,
        "cost_per_1000_triaged_usd": cost / len(all_tr) * 1000,
    }


def triage_detail(src: Source, triage_id: int) -> dict | None:
    """One triage record with its redacted complaint text, ready for the detail panel."""
    df = load_frame(src, "triage_records", TRIAGE_DETAIL_COLS, ids=[int(triage_id)])
    if df.empty:
        return None
    rec = df.iloc[0].to_dict()
    rec["output"] = redact_obj(_decode_json(rec.get("output")) or {})
    rec["confidence_signals"] = redact_obj(_decode_json(rec.get("confidence_signals")) or {})
    rec["cited_sources"] = _as_list(rec.get("cited_sources"))
    rec["recall_campaigns"] = _as_list(rec.get("recall_campaigns"))
    rec["complaint_text"] = complaint_text(src, int(rec["odi_number"]))
    return rec


def complaint_text(src: Source, odi_number: int) -> str | None:
    """Complaint narrative after PII redaction, or None when it is not available in this source."""
    if src.mode == "live":
        with src.engine.connect() as conn:
            text = conn.execute(select(db.complaints.c.summary)
                                .where(db.complaints.c.odi_number == int(odi_number))).scalar()
    elif src.mode == "demo":
        df = read_snapshot(src.demo_dir, "complaint_texts")
        hit = df[df["odi_number"] == int(odi_number)] if not df.empty else df
        text = None if hit.empty else hit.iloc[0]["summary"]
    else:
        text = None
    return None if text is None else redact(str(text)).text


def recalls_for(src: Source, campaigns: list[str]) -> pd.DataFrame:
    df = load_frame(src, "recalls", RECALL_COLS)
    df = df[df["campaign_number"].isin(campaigns)]
    if df.empty:
        return pd.DataFrame(columns=["campaign_number", "component_raw", "report_date", "summary", "url"])
    g = (df.sort_values("model_year").groupby("campaign_number", as_index=False)
         .agg(component_raw=("component_raw", "first"), report_date=("report_date", "first"),
              summary=("summary", "first"),
              vehicles=("model", lambda s: ", ".join(sorted(set(s))))))
    g["url"] = g["campaign_number"].map(recall_url)
    return g


def recall_url(campaign: str) -> str:
    return NHTSA_RECALL_URL.format(campaign=campaign)


def review_counts(src: Source) -> dict:
    df = load_frame(src, "review_queue", ("status",))
    counts = df["status"].value_counts().to_dict() if not df.empty else {}
    return {s: int(counts.get(s, 0)) for s in ("pending", "accepted", "corrected")}


def pending_reviews(src: Source, limit: int = 20) -> pd.DataFrame:
    """Pending review items (lowest confidence first) plus the recall candidates the agent saw.
    Live mode uses vsia.review.pending(); demo mode rebuilds the same columns from the snapshot."""
    if src.mode == "live":
        from vsia import review
        df = review.pending(limit=limit)
        if df.empty:
            df = pd.DataFrame(columns=PENDING_COLS)
    elif src.mode == "demo":
        rq = load_frame(src, "review_queue", ("id", "odi_number", "triage_record_id", "status", "reason",
                                               "created_at"))
        rq = rq[rq["status"] == "pending"].rename(columns={"id": "queue_id"})
        tr = load_frame(src, "triage_records", ("id", "component", "severity", "recall_campaigns", "confidence",
                                                 "provider"))
        comp = load_frame(src, "complaints", ("odi_number", "make", "model", "model_year"))
        texts = read_snapshot(src.demo_dir, "complaint_texts")
        if texts.empty:
            texts = pd.DataFrame(columns=["odi_number", "summary"])
        df = (rq.merge(tr, left_on="triage_record_id", right_on="id", how="inner")
              .merge(comp, on="odi_number", how="inner").merge(texts, on="odi_number", how="left"))
        df = df.sort_values("confidence").head(limit)
        df = df.reindex(columns=PENDING_COLS)
    else:
        return pd.DataFrame(columns=[*PENDING_COLS, "candidates", "review_reasons"])
    df = df.reset_index(drop=True)
    sig = load_frame(src, "triage_records", ("id", "confidence_signals"),
                     ids=[int(i) for i in df["triage_record_id"].dropna()])
    sig_by_id = {int(r.id): (_decode_json(r.confidence_signals) or {}) for r in sig.itertuples()}
    df["candidates"] = [list((sig_by_id.get(int(i), {}) or {}).get("candidates") or [])
                        for i in df["triage_record_id"]]
    df["review_reasons"] = [list((sig_by_id.get(int(i), {}) or {}).get("review_reasons") or [])
                            for i in df["triage_record_id"]]
    df["recall_campaigns"] = df["recall_campaigns"].map(_as_list)
    df["summary"] = df["summary"].map(lambda t: None if t is None or (isinstance(t, float) and pd.isna(t))
                                      else redact(str(t)).text)
    return df


class ReadOnlyError(RuntimeError):
    pass


def submit_review(src: Source, decision) -> dict:
    """Persist one analyst decision through vsia.review.decide(). Refused in read-only or demo mode."""
    if src.readonly or src.mode != "live":
        raise ReadOnlyError("the dashboard is in read-only mode; review decisions are disabled")
    from vsia import review
    result = review.decide(decision)
    clear_cache()
    return result


# --------------------------------------------------------------------------------------------------
# Forecasts and spikes
# --------------------------------------------------------------------------------------------------

FORECAST_COLS = ("run_id", "component", "week", "actual", "forecast", "lower", "upper", "model_name",
                 "is_holdout", "created_at")


def latest_forecasts(src: Source) -> pd.DataFrame:
    """Forecast rows of the most recent run_id (by created_at)."""
    df = load_frame(src, "forecasts", FORECAST_COLS)
    if df.empty:
        return df
    last = df.sort_values("created_at").iloc[-1]["run_id"]
    out = df[df["run_id"] == last].copy()
    out["is_holdout"] = out["is_holdout"].astype(bool)
    return out.sort_values(["component", "week"]).reset_index(drop=True)


def spike_alerts(src: Source) -> pd.DataFrame:
    """All spike alerts, newest week first, with an `active` flag: flagged in the last RECENT_ALERT_WEEKS
    complete weeks of the latest forecast holdout window (the forecast pipeline's "current" alerts)."""
    df = load_frame(src, "spike_alerts", ("id", "run_id", "component", "week", "actual", "upper", "ratio",
                                           "created_at"))
    if df.empty:
        df["active"] = pd.Series(dtype=bool)
        return df
    fc = latest_forecasts(src)
    hold = fc[fc["is_holdout"]] if not fc.empty else fc
    last_week = hold["week"].max() if not hold.empty else df["week"].max()
    df["active"] = df["week"] > last_week - pd.Timedelta(weeks=RECENT_ALERT_WEEKS)
    return df.sort_values(["week", "ratio"], ascending=[False, False]).reset_index(drop=True)


# --------------------------------------------------------------------------------------------------
# Evaluation, routing and LLM cost
# --------------------------------------------------------------------------------------------------

def eval_table(src: Source) -> pd.DataFrame:
    """One row per eval run with metrics flattened to columns. eval/run_eval.py stores the whole run dict
    (provider, model, split, metrics, ...) in eval_runs.metrics; a flat metrics dict is also accepted."""
    df = load_frame(src, "eval_runs", ("id", "run_id", "provider", "model", "metrics", "created_at"))
    if df.empty:
        return pd.DataFrame(columns=["run_id", "provider", "model", "split", "created_at", "is_latest"])
    rows = []
    for r in df.itertuples():
        blob = _decode_json(r.metrics) or {}
        metrics = blob.get("metrics") if isinstance(blob.get("metrics"), dict) else blob
        flat = {k: v for k, v in metrics.items() if isinstance(v, (int, float)) or v is None}
        rows.append({"run_id": r.run_id, "provider": r.provider, "model": r.model,
                     "split": blob.get("split", "gold"), "prompt_version": blob.get("prompt_version"),
                     "created_at": r.created_at, **flat})
    out = pd.DataFrame(rows).sort_values("created_at", ascending=False).reset_index(drop=True)
    out["is_latest"] = ~out.duplicated(["provider", "model", "split"], keep="first")
    return out


def routing_curves(src: Source) -> list[dict]:
    """Threshold curves written by `eval.run_eval calibrate` (data/models/routing_<provider>.json)."""
    folder = src.demo_dir if src.mode == "demo" else vconfig.DATA_DIR / "models"
    out = []
    for p in sorted(folder.glob("routing_*.json")) if folder.exists() else []:
        try:
            d = json.loads(p.read_text())
        except ValueError:
            continue
        d.setdefault("provider", p.stem.removeprefix("routing_"))
        out.append({k: d.get(k) for k in ("provider", "threshold", "coverage", "accuracy_auto",
                                          "target_auto_accuracy", "fitted_at", "curve", "note")})
    return out


def llm_summary(src: Source) -> pd.DataFrame:
    """Cost and latency per (provider, model, purpose) from vsia.observability.cost_latency_summary()."""
    if src.mode == "live":
        from vsia import observability
        df = observability.cost_latency_summary()
    elif src.mode == "demo":
        df = read_snapshot(src.demo_dir, "llm_cost_summary")
    else:
        df = pd.DataFrame()
    return df.reindex(columns=LLM_SUMMARY_COLS) if df.empty else df


# --------------------------------------------------------------------------------------------------
# Overview KPIs
# --------------------------------------------------------------------------------------------------

def kpis(src: Source) -> dict:
    comp_n = len(load_frame(src, "complaints", ("odi_number",)))
    tri = triage_summary(src)
    rev = review_counts(src)
    alerts = spike_alerts(src)
    llm = llm_summary(src)
    llm_cost = float(pd.to_numeric(llm["total_cost_usd"], errors="coerce").fillna(0).sum()) if not llm.empty \
        else 0.0
    return {
        "complaints": comp_n,
        "last_ingestion": latest_ingestion(src),
        **tri,
        "pending_reviews": rev["pending"],
        "active_spike_alerts": int(alerts["active"].sum()) if not alerts.empty else 0,
        "spike_alerts_total": len(alerts),
        "llm_calls": int(pd.to_numeric(llm["calls"], errors="coerce").fillna(0).sum()) if not llm.empty else 0,
        "llm_cost_usd": llm_cost,
    }


def taxonomy() -> list[str]:
    return vconfig.components()


def severity_levels() -> dict[str, str]:
    return vconfig.severity_levels()


# --------------------------------------------------------------------------------------------------
# Streamlit caching (st.cache_data with a TTL). Tests call the plain functions above.
# --------------------------------------------------------------------------------------------------

try:
    import streamlit as st

    @st.cache_data(ttl=CACHE_TTL_S, show_spinner=False, max_entries=256)
    def _cached_call(fn_name: str, key: str, args: tuple, _src: Source):
        return globals()[fn_name](_src, *args)

    def clear_cache() -> None:
        _cached_call.clear()

except ImportError:  # pragma: no cover - the dashboard always has streamlit; scripts and tests may not
    def _cached_call(fn_name: str, key: str, args: tuple, _src: Source):
        return globals()[fn_name](_src, *args)

    def clear_cache() -> None:
        return None


def cached(fn, src: Source, *args):
    """Call a loader through the shared cache. The cache key is the function name, the source key and
    the (hashable) arguments; the Source object itself is not hashed."""
    return _cached_call(fn.__name__, src.key, tuple(args), src)


def snapshot_manifest(src: Source) -> dict | None:
    p = src.demo_dir / "manifest.json"
    if src.mode != "demo" or not p.exists():
        return None
    return json.loads(p.read_text())


def fmt_ts(v: Any) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
        return "n/a"
    if isinstance(v, (datetime, pd.Timestamp)):
        return pd.Timestamp(v).strftime("%Y-%m-%d %H:%M UTC")
    return str(v)
