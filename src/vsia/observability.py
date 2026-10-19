"""LLM observability (FR-11): cost and latency reporting over llm_calls, plus a tiny span timer.

The gateway (vsia.llm) writes one llm_calls row per complete_json() call: provider, model, purpose,
token counts, cost, latency, ok/error, prompt version and a reference id. Never prompt or reply text.
This module reads that table with SQLAlchemy Core (portable SQLite/Postgres) and returns pandas
DataFrames for the dashboard, the eval report and the cost model.

timed() covers non-LLM spans (retrieval, tool calls, parsing). It logs one structured line per span
through Python logging, with attribute names that follow the OpenTelemetry GenAI semantic conventions
(Development stability, now in open-telemetry/semantic-conventions-genai), so a later switch to a real
OTel exporter is a logging-handler change. No dependency beyond the standard library and pandas.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import select

from vsia.db import engine, llm_calls

log = logging.getLogger("vsia.observability")

SUMMARY_COLUMNS = [
    "provider", "model", "purpose", "calls", "errors", "error_rate", "total_cost_usd",
    "cost_per_1k_calls_usd", "p50_latency_ms", "p95_latency_ms", "avg_input_tokens", "avg_output_tokens",
]

# Attribute keys that could carry prompt, completion or query text. timed() replaces their values,
# because span logs must hold metadata only (AGENTS.md rule 4, OWASP LLM02).
_TEXT_ATTRIBUTES = {
    "gen_ai.prompt", "gen_ai.completion", "gen_ai.input.messages", "gen_ai.output.messages",
    "gen_ai.system_instructions", "gen_ai.retrieval.query.text", "gen_ai.tool.call.arguments",
    "gen_ai.tool.call.result", "prompt", "completion", "text", "query", "content",
}


def _load_calls(since: datetime | None = None) -> pd.DataFrame:
    stmt = select(llm_calls)
    if since is not None:
        stmt = stmt.where(llm_calls.c.created_at >= since)
    with engine().connect() as conn:
        rows = conn.execute(stmt).mappings().all()
    return pd.DataFrame([dict(r) for r in rows], columns=[c.name for c in llm_calls.columns])


def cost_latency_summary(since: datetime | None = None) -> pd.DataFrame:
    """One row per (provider, model, purpose): call count, error rate, total cost, cost per 1,000 calls,
    p50/p95 latency and average tokens. Failed calls count toward cost and latency, because a failed
    call still spends tokens and time. Empty frame with the same columns when nothing is logged."""
    df = _load_calls(since)
    if df.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)
    df["ok"] = df["ok"].fillna(False).astype(bool)
    for col in ("input_tokens", "output_tokens", "latency_ms", "cost_usd"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    g = df.groupby(["provider", "model", "purpose"], dropna=False)
    out = g.agg(
        calls=("id", "count"),
        errors=("ok", lambda s: int((~s).sum())),
        total_cost_usd=("cost_usd", "sum"),
        p50_latency_ms=("latency_ms", lambda s: float(s.quantile(0.50))),
        p95_latency_ms=("latency_ms", lambda s: float(s.quantile(0.95))),
        avg_input_tokens=("input_tokens", "mean"),
        avg_output_tokens=("output_tokens", "mean"),
    ).reset_index()
    out["error_rate"] = out["errors"] / out["calls"]
    out["cost_per_1k_calls_usd"] = out["total_cost_usd"] / out["calls"] * 1000
    out["total_cost_usd"] = out["total_cost_usd"].round(6)
    out["cost_per_1k_calls_usd"] = out["cost_per_1k_calls_usd"].round(6)
    out["error_rate"] = out["error_rate"].round(4)
    out["avg_input_tokens"] = out["avg_input_tokens"].round(1)
    out["avg_output_tokens"] = out["avg_output_tokens"].round(1)
    return out[SUMMARY_COLUMNS].sort_values(["provider", "model", "purpose"]).reset_index(drop=True)


def cost_per_1000(provider: str, model: str, purpose: str = "triage") -> float | None:
    """Measured cost in USD of 1,000 calls for one provider, model and purpose (for example 1,000
    complaint triages). None when no such calls are logged: an unmeasured cost is not zero."""
    stmt = select(llm_calls.c.cost_usd).where(
        llm_calls.c.provider == provider, llm_calls.c.model == model, llm_calls.c.purpose == purpose)
    with engine().connect() as conn:
        costs = [float(r[0] or 0.0) for r in conn.execute(stmt)]
    if not costs:
        return None
    return round(sum(costs) / len(costs) * 1000, 6)


def llm_call_attributes(call: Any) -> dict[str, Any]:
    """Map a vsia.schemas.LLMCall to OpenTelemetry GenAI attribute names (metadata only)."""
    return {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": call.provider,
        "gen_ai.system": call.provider,  # older name for gen_ai.provider.name, kept for older backends
        "gen_ai.request.model": call.model,
        "gen_ai.usage.input_tokens": call.input_tokens,
        "gen_ai.usage.output_tokens": call.output_tokens,
        "gen_ai.prompt.version": call.prompt_version,
        "vsia.purpose": call.purpose,
        "vsia.cost_usd": call.cost_usd,
        "vsia.ref_id": call.ref_id,
        "duration_ms": call.latency_ms,
        "status": "ok" if call.ok else "error",
    }


def _scrub(attrs: dict[str, Any]) -> dict[str, Any]:
    from vsia.guardrails import redact

    clean: dict[str, Any] = {}
    for k, v in attrs.items():
        if k in _TEXT_ATTRIBUTES:
            clean[k] = "[omitted]"
        elif isinstance(v, str):
            clean[k] = redact(v).text
        else:
            clean[k] = v
    return clean


@contextmanager
def timed(operation: str, logger: logging.Logger | None = None, **attributes: Any) -> Iterator[dict]:
    """Time a non-LLM span and log it once at INFO when it ends.

    Usage:
        with timed("retrieval", **{"gen_ai.data_source.id": "recalls", "gen_ai.retrieval.top_k": 5}) as span:
            hits = search(...)
            span["vsia.hits"] = len(hits)

    Keyword names with dots must be passed through a dict, as above. The yielded dict can be extended
    inside the block. Errors are recorded as status=error plus error.type and re-raised. Text-bearing
    keys (prompt, query text, tool arguments) are replaced with [omitted]; other strings pass through
    vsia.guardrails.redact()."""
    span: dict[str, Any] = {"gen_ai.operation.name": operation, "span.id": uuid.uuid4().hex[:16]}
    span.update(attributes)
    started = time.perf_counter()
    try:
        yield span
        span.setdefault("status", "ok")
    except BaseException as exc:
        span["status"] = "error"
        span["error.type"] = type(exc).__name__
        raise
    finally:
        span["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
        clean = _scrub(span)
        (logger or log).info("span %s %s", operation, json.dumps(clean, default=str, sort_keys=True),
                             extra={"vsia_span": clean})
