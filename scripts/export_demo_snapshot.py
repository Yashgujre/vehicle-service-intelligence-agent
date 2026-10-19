"""Export a small, redacted snapshot of the dashboard tables to app/demo_data/ (parquet).

The public Streamlit Community Cloud deploy cannot reach the laptop database, so it reads this snapshot
instead (VSIA_DEMO_SNAPSHOT=1, or automatically when no database is reachable). See
docs/decisions/0072-demo-snapshot-for-public-dashboard.md.

What is exported:
  complaints        narrow columns for every complaint (no narrative text)
  complaint_texts   redacted narratives only for complaints in the triage and review snapshot
  triage_records    latest record per complaint, newest first, capped (--max-triage), plus any record a
                    pending review points at; free text inside JSON is redacted
  review_queue, recalls, ingestion_runs (without the details blob), forecasts (latest run),
  spike_alerts, eval_runs, llm_cost_summary (aggregates from vsia.observability; no per-call rows)
  routing_<provider>.json copied from data/models/
  manifest.json     export time, row counts and file sizes

No environment values, keys or connection strings are written. The script fails if the snapshot exceeds
--max-mb (default 10).

Usage (repo root, venv active):
    python scripts/export_demo_snapshot.py [--out app/demo_data] [--max-triage 3000] [--max-mb 10]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT / "app", REPO_ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import data as app_data
from vsia import config as vconfig
from vsia.guardrails import redact

JSON_COLUMNS = {
    "triage_records": ["recall_campaigns", "confidence_signals", "output", "cited_sources"],
    "eval_runs": ["metrics"],
}


def _to_json_str(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return json.dumps(v, default=str)


def _write(df: pd.DataFrame, out: Path, name: str) -> int:
    df = df.copy()
    for c in JSON_COLUMNS.get(name, []):
        if c in df.columns:
            df[c] = df[c].map(_to_json_str)
    path = out / f"{name}.parquet"
    df.to_parquet(path, index=False, compression="zstd")
    return len(df)


def export(src: app_data.Source, out: Path, max_triage: int = 3000, max_mb: float = 10.0) -> dict:
    if src.mode != "live":
        raise SystemExit(f"export needs a live database; current source: {src.reason}")
    if out.exists():
        for p in out.glob("*"):
            if p.is_file():
                p.unlink()
    out.mkdir(parents=True, exist_ok=True)
    rows: dict[str, int] = {}

    comp = app_data.load_frame(src, "complaints", app_data.COMPLAINT_COLS)
    rows["complaints"] = _write(comp, out, "complaints")

    rq = app_data.load_frame(src, "review_queue", ("id", "odi_number", "triage_record_id", "status", "reason",
                                                   "created_at", "resolved_at"))
    rq["reason"] = rq["reason"].map(lambda t: redact(t).text if isinstance(t, str) else t)
    rows["review_queue"] = _write(rq, out, "review_queue")

    tr_all = app_data.load_frame(src, "triage_records", ("id", "odi_number", "created_at"))
    keep_ids: set[int] = set()
    if not tr_all.empty:
        latest = (tr_all.sort_values(["created_at", "id"]).drop_duplicates("odi_number", keep="last")
                  .sort_values(["created_at", "id"], ascending=False).head(max_triage))
        keep_ids = set(latest["id"].astype(int))
    pending_ids = set(rq.loc[rq["status"] == "pending", "triage_record_id"].dropna().astype(int))
    keep_ids |= pending_ids
    tr = app_data.load_frame(src, "triage_records", app_data.TRIAGE_DETAIL_COLS, ids=sorted(keep_ids))
    for c in ("output", "confidence_signals"):
        tr[c] = tr[c].map(app_data.redact_obj)
    rows["triage_records"] = _write(tr, out, "triage_records")

    odis = sorted(set(tr["odi_number"].astype(int)) | set(rq["odi_number"].astype(int)))
    texts = pd.DataFrame({"odi_number": odis,
                          "summary": [app_data.complaint_text(src, o) for o in odis]})
    rows["complaint_texts"] = _write(texts, out, "complaint_texts")

    rows["recalls"] = _write(app_data.load_frame(src, "recalls", app_data.RECALL_COLS), out, "recalls")
    ing = app_data.load_frame(src, "ingestion_runs", ("id", "kind", "started_at", "finished_at", "rows_fetched",
                                                      "rows_inserted", "rows_skipped_duplicate", "rows_filtered",
                                                      "ok"))
    rows["ingestion_runs"] = _write(ing, out, "ingestion_runs")
    rows["forecasts"] = _write(app_data.latest_forecasts(src), out, "forecasts")
    alerts = app_data.load_frame(src, "spike_alerts", ("id", "run_id", "component", "week", "actual", "upper",
                                                       "ratio", "created_at"))
    rows["spike_alerts"] = _write(alerts, out, "spike_alerts")
    ev = app_data.load_frame(src, "eval_runs", ("id", "run_id", "provider", "model", "metrics", "created_at"))
    rows["eval_runs"] = _write(ev, out, "eval_runs")
    rows["llm_cost_summary"] = _write(app_data.llm_summary(src), out, "llm_cost_summary")

    models_dir = vconfig.DATA_DIR / "models"
    routing = sorted(models_dir.glob("routing_*.json")) if models_dir.exists() else []
    for p in routing:
        shutil.copy2(p, out / p.name)

    sizes = {p.name: p.stat().st_size for p in sorted(out.iterdir()) if p.is_file()}
    total = sum(sizes.values())
    manifest = {
        "exported_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "source_backend": src.engine.url.get_backend_name(),
        "rows": rows,
        "routing_files": [p.name for p in routing],
        "bytes": sizes,
        "total_bytes": total,
        "redaction": "complaint narratives and free-text model output passed through vsia.guardrails.redact",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    if total > max_mb * 1024 * 1024:
        raise SystemExit(f"snapshot is {total / 1e6:.1f} MB, above the {max_mb} MB limit; lower --max-triage")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=app_data.DEMO_DIR)
    ap.add_argument("--max-triage", type=int, default=3000)
    ap.add_argument("--max-mb", type=float, default=10.0)
    a = ap.parse_args(argv)
    src = app_data.resolve_source(demo_dir=a.out)
    if src.mode != "live":
        print(f"No live database: {src.reason}", file=sys.stderr)
        return 1
    m = export(src, a.out, a.max_triage, a.max_mb)
    print(json.dumps({k: m[k] for k in ("exported_at", "rows", "total_bytes")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
