"""Storage layer. SQLAlchemy Core tables that run unchanged on SQLite (laptop) and Postgres (VM).

Table ownership:
  complaints, recalls, ingestion_runs          -> ingestion (vsia.ingest)
  recall_documents                             -> document parsing (vsia.documents)
  triage_records, review_queue, labels         -> triage agent and human review (vsia.agent, vsia.review)
  llm_calls                                    -> LLM gateway (vsia.llm)
  forecasts, spike_alerts                      -> forecasting (pipelines/forecast.py)
  eval_runs                                    -> evaluation (eval/run_eval.py)
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    insert,
)
from sqlalchemy.engine import Engine

from vsia.config import DATA_DIR, env

metadata = MetaData()

complaints = Table(
    "complaints", metadata,
    Column("odi_number", Integer, primary_key=True),
    Column("make", String(64), nullable=False, index=True),
    Column("model", String(128), nullable=False, index=True),
    Column("model_year", Integer, nullable=False, index=True),
    Column("manufacturer", String(128)),
    Column("date_filed", Date, index=True),
    Column("date_incident", Date),
    Column("crash", Boolean, default=False),
    Column("fire", Boolean, default=False),
    Column("injuries", Integer, default=0),
    Column("deaths", Integer, default=0),
    Column("vin_prefix", String(17)),
    Column("components_raw", Text),
    Column("component_primary", String(64), index=True),
    Column("summary", Text, nullable=False),
    Column("ingested_at", DateTime, default=datetime.utcnow),
    Column("source", String(32), default="api"),
)

recalls = Table(
    "recalls", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("campaign_number", String(16), nullable=False, index=True),
    Column("make", String(64), nullable=False),
    Column("model", String(128), nullable=False),
    Column("model_year", Integer, nullable=False),
    Column("manufacturer", String(128)),
    Column("report_date", Date),
    Column("component_raw", Text),
    Column("component_primary", String(64), index=True),
    Column("summary", Text),
    Column("consequence", Text),
    Column("remedy", Text),
    Column("park_it", Boolean, default=False),
    Column("park_outside", Boolean, default=False),
    Column("ota", Boolean, default=False),
    UniqueConstraint("campaign_number", "make", "model", "model_year", name="uq_recall_vehicle"),
)

recall_documents = Table(
    "recall_documents", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("campaign_number", String(16), nullable=False, index=True),
    Column("doc_type", String(32)),
    Column("source_url", Text),
    Column("parser", String(32)),
    Column("pages", Integer),
    Column("markdown", Text),
    Column("extraction", JSON),
    Column("extraction_valid", Boolean),
    Column("parsed_at", DateTime, default=datetime.utcnow),
)

triage_records = Table(
    "triage_records", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("odi_number", Integer, nullable=False, index=True),
    Column("run_id", String(64), index=True),
    Column("schema_version", String(8)),
    Column("component", String(64), index=True),
    Column("severity", String(4)),
    Column("recall_campaigns", JSON),
    Column("confidence", Float),
    Column("confidence_signals", JSON),
    Column("route", String(8), index=True),
    Column("output", JSON),
    Column("cited_sources", JSON),
    Column("provider", String(32)),
    Column("model", String(64)),
    Column("prompt_version", String(16)),
    Column("latency_ms", Integer),
    Column("cost_usd", Float),
    Column("created_at", DateTime, default=datetime.utcnow),
)

review_queue = Table(
    "review_queue", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("odi_number", Integer, nullable=False, index=True),
    Column("triage_record_id", Integer, index=True),
    Column("status", String(16), default="pending", index=True),  # pending | accepted | corrected
    Column("reason", Text),
    Column("created_at", DateTime, default=datetime.utcnow),
    Column("resolved_at", DateTime),
)

labels = Table(
    "labels", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("odi_number", Integer, nullable=False, index=True),
    Column("component", String(64)),
    Column("severity", String(4)),
    Column("recall_campaigns", JSON),
    Column("source", String(32)),  # review | gold_hand | gold_silver
    Column("reviewer", String(64)),
    Column("note", Text),
    Column("created_at", DateTime, default=datetime.utcnow),
)

llm_calls = Table(
    "llm_calls", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("provider", String(32), index=True),
    Column("model", String(64), index=True),
    Column("purpose", String(32), index=True),
    Column("input_tokens", Integer),
    Column("output_tokens", Integer),
    Column("cost_usd", Float),
    Column("latency_ms", Integer),
    Column("ok", Boolean),
    Column("error", Text),
    Column("prompt_version", String(16)),
    Column("ref_id", String(64)),
    Column("created_at", DateTime, default=datetime.utcnow, index=True),
)

ingestion_runs = Table(
    "ingestion_runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kind", String(32)),  # complaints_api | complaints_backfill | recalls
    Column("started_at", DateTime),
    Column("finished_at", DateTime),
    Column("rows_fetched", Integer),
    Column("rows_inserted", Integer),
    Column("rows_skipped_duplicate", Integer),
    Column("rows_filtered", Integer),
    Column("ok", Boolean),
    Column("error", Text),
    Column("details", JSON),
)

forecasts = Table(
    "forecasts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String(64), index=True),
    Column("component", String(64), index=True),
    Column("week", Date, index=True),
    Column("actual", Float),
    Column("forecast", Float),
    Column("lower", Float),
    Column("upper", Float),
    Column("model_name", String(64)),
    Column("is_holdout", Boolean),
    Column("created_at", DateTime, default=datetime.utcnow),
)

spike_alerts = Table(
    "spike_alerts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String(64), index=True),
    Column("component", String(64)),
    Column("week", Date),
    Column("actual", Float),
    Column("upper", Float),
    Column("ratio", Float),
    Column("created_at", DateTime, default=datetime.utcnow),
)

eval_runs = Table(
    "eval_runs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String(64), index=True),
    Column("provider", String(32)),
    Column("model", String(64)),
    Column("metrics", JSON),
    Column("created_at", DateTime, default=datetime.utcnow),
)


@lru_cache
def engine() -> Engine:
    url = env().database_url
    if url.startswith("sqlite"):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    eng = create_engine(url, future=True, pool_pre_ping=True)
    metadata.create_all(eng)
    return eng


def log_llm_call(call) -> None:
    """Persist one LLM call (vsia.schemas.LLMCall). Never raises: logging must not break triage."""
    try:
        with engine().begin() as conn:
            conn.execute(insert(llm_calls).values(**call.model_dump()))
    except Exception:  # noqa: BLE001
        pass
