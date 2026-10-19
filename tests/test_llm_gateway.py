"""Tests for the LLM gateway (vsia.llm) and LLM observability (vsia.observability). No network: provider
functions are replaced in llm._PROVIDERS and DATABASE_URL points at a temporary SQLite file."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, select

from vsia import config
from vsia.schemas import LLMCall, TriageOutput

VALID_TRIAGE = {
    "extracted": {"make": "TESLA", "model": "MODEL Y", "model_year": 2023,
                  "symptom": "Phantom braking at highway speed", "mileage": 45000, "speed_context": "moving"},
    "component": "FORWARD COLLISION AVOIDANCE",
    "secondary_components": [],
    "severity": "S2",
    "severity_reason": "Unintended braking while moving without a crash",
    "recall_matches": [],
    "model_confidence": 0.8,
    "injection_suspected": False,
}


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Fresh SQLite database per test; caches cleared so vsia.db.engine() picks up the new URL."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test_vsia.db'}")
    from vsia import db

    config.env.cache_clear()
    db.engine.cache_clear()
    yield db
    db.engine.cache_clear()
    config.env.cache_clear()


def _rows(db):
    with db.engine().connect() as conn:
        return [dict(r) for r in conn.execute(select(db.llm_calls)).mappings()]


# ------------------------------------------------------------------------------------------------
# provider_schema()
# ------------------------------------------------------------------------------------------------


def _object_nodes(node):
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            yield node
        for k, v in node.items():
            if k == "properties":
                for prop in v.values():
                    yield from _object_nodes(prop)
            else:
                yield from _object_nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _object_nodes(v)


def _all_keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            if k == "properties":
                for prop in v.values():
                    yield from _all_keys(prop)
            else:
                yield from _all_keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _all_keys(v)


def test_provider_schema_strict_for_triage_output():
    from vsia.llm import _STRIP_KEYS, provider_schema

    schema = provider_schema(TriageOutput, strict=True)
    objects = list(_object_nodes(schema))
    # TriageOutput, ExtractedFields and RecallMatch
    assert len(objects) >= 3
    for node in objects:
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])
    assert not (_STRIP_KEYS & set(_all_keys(schema)))
    assert set(schema["properties"]) == set(TriageOutput.model_fields)


def test_provider_schema_non_strict_keeps_pydantic_required():
    from vsia.llm import provider_schema

    schema = provider_schema(TriageOutput, strict=False)
    for node in _object_nodes(schema):
        assert node["additionalProperties"] is False
    extracted = schema["$defs"]["ExtractedFields"]
    assert extracted["required"] == ["symptom"]


def test_provider_schema_does_not_mutate_pydantic_cache():
    from vsia.llm import provider_schema

    before = json.dumps(TriageOutput.model_json_schema(), sort_keys=True)
    provider_schema(TriageOutput, strict=True)
    assert json.dumps(TriageOutput.model_json_schema(), sort_keys=True) == before


# ------------------------------------------------------------------------------------------------
# price()
# ------------------------------------------------------------------------------------------------


def test_price_math(monkeypatch):
    from vsia import llm

    fake = {"llm": {"providers": {
        "paid": {"price_per_mtok": {"input": 0.10, "output": 0.50}},
        "free": {"price_per_mtok": {"input": 0.0, "output": 0.0}},
    }}}
    monkeypatch.setattr(config, "settings", lambda: fake)
    assert llm.price("paid", 1_000_000, 1_000_000) == pytest.approx(0.60)
    assert llm.price("paid", 2_000, 500) == pytest.approx(2_000 / 1e6 * 0.10 + 500 / 1e6 * 0.50)
    assert llm.price("paid", 0, 0) == 0
    assert llm.price("free", 10_000, 10_000) == 0
    assert llm.price("unknown-provider", 10_000, 10_000) == 0


def test_price_uses_configured_table():
    from vsia import llm

    p = config.settings()["llm"]["providers"]["anthropic"]["price_per_mtok"]
    expected = 1_200 / 1e6 * p["input"] + 300 / 1e6 * p["output"]
    assert llm.price("anthropic", 1_200, 300) == pytest.approx(expected)


# ------------------------------------------------------------------------------------------------
# complete_json(): validation and repair retry
# ------------------------------------------------------------------------------------------------


def _fake_provider(replies, seen):
    def fn(model, system, user, schema, max_tokens, temperature):
        seen.append({"model": model, "user": user, "schema": schema})
        return replies[len(seen) - 1], 100, 20
    return fn


def test_complete_json_repairs_invalid_json_on_second_attempt(tmp_db, monkeypatch):
    from vsia import llm

    seen: list[dict] = []
    monkeypatch.setitem(llm._PROVIDERS, "anthropic",
                        _fake_provider(["this is not json", json.dumps(VALID_TRIAGE)], seen))
    res = llm.complete_json("sys", "user text", TriageOutput, purpose="triage", provider="anthropic",
                            model="test-model", prompt_version="t1", ref_id="123")
    assert isinstance(res.data, TriageOutput)
    assert res.data.severity == "S2"
    assert len(seen) == 2
    assert "rejected by the validator" in seen[1]["user"]
    assert res.call.ok and res.call.input_tokens == 200 and res.call.output_tokens == 40
    assert res.call.cost_usd == pytest.approx(llm.price("anthropic", 200, 40))
    rows = _rows(tmp_db)
    assert len(rows) == 1 and rows[0]["ok"] and rows[0]["ref_id"] == "123"


def test_complete_json_repairs_schema_violation(tmp_db, monkeypatch):
    from vsia import llm

    bad = dict(VALID_TRIAGE, severity="S9")
    seen: list[dict] = []
    monkeypatch.setitem(llm._PROVIDERS, "ollama", _fake_provider([json.dumps(bad), json.dumps(VALID_TRIAGE)], seen))
    res = llm.complete_json("sys", "user", TriageOutput, purpose="triage", provider="ollama", model="m")
    assert res.call.ok and len(seen) == 2


def test_complete_json_both_invalid_raises_and_logs_failure(tmp_db, monkeypatch):
    from vsia import llm

    seen: list[dict] = []
    monkeypatch.setitem(llm._PROVIDERS, "ollama", _fake_provider(["nope", "{\"still\": \"wrong\"}"], seen))
    with pytest.raises(llm.LLMError):
        llm.complete_json("sys", "user", TriageOutput, purpose="triage", provider="ollama", model="m",
                          ref_id="999")
    assert len(seen) == 2
    rows = _rows(tmp_db)
    assert len(rows) == 1
    row = rows[0]
    assert row["ok"] is False or row["ok"] == 0
    assert row["input_tokens"] == 200 and row["purpose"] == "triage" and row["ref_id"] == "999"
    assert "invalid output (attempt 2)" in row["error"]


def test_complete_json_provider_exception_is_logged_without_retry(tmp_db, monkeypatch):
    from vsia import llm

    calls = []

    def boom(*args):
        calls.append(1)
        raise RuntimeError("provider down")

    monkeypatch.setitem(llm._PROVIDERS, "ollama", boom)
    with pytest.raises(llm.LLMError, match="provider down"):
        llm.complete_json("sys", "user", TriageOutput, purpose="triage", provider="ollama", model="m")
    assert len(calls) == 1
    assert _rows(tmp_db)[0]["ok"] in (False, 0)


def test_complete_json_rejects_unknown_provider(tmp_db):
    from vsia import llm

    with pytest.raises(llm.LLMError):
        llm.complete_json("s", "u", TriageOutput, purpose="triage", provider="heuristic", model="m")


def test_llm_calls_never_store_prompt_text(tmp_db, monkeypatch):
    from vsia import llm

    secret = "UNIQUE-PROMPT-MARKER-42"
    monkeypatch.setitem(llm._PROVIDERS, "ollama", _fake_provider([json.dumps(VALID_TRIAGE)], []))
    llm.complete_json(f"system {secret}", f"user {secret}", TriageOutput, purpose="triage",
                      provider="ollama", model="m")
    assert secret not in json.dumps(_rows(tmp_db), default=str)


# ------------------------------------------------------------------------------------------------
# observability
# ------------------------------------------------------------------------------------------------


def _utc_naive() -> datetime:
    """llm_calls.created_at holds naive UTC (vsia.db uses datetime.utcnow as the column default)."""
    return datetime.now(UTC).replace(tzinfo=None)


def _log(db, **kw):
    base = {"provider": "anthropic", "model": "test-model", "purpose": "triage", "input_tokens": 1000,
            "output_tokens": 200, "cost_usd": 0.0002, "latency_ms": 100, "ok": True}
    base.update(kw)
    db.log_llm_call(LLMCall(**base))


def test_cost_latency_summary(tmp_db):
    from vsia.observability import SUMMARY_COLUMNS, cost_latency_summary

    for ms in (100, 200, 300, 400):
        _log(tmp_db, latency_ms=ms)
    _log(tmp_db, latency_ms=1000, ok=False, error="timeout", cost_usd=0.0001)
    _log(tmp_db, provider="ollama", model="qwen2.5:3b", cost_usd=0.0, latency_ms=2000)

    df = cost_latency_summary()
    assert list(df.columns) == SUMMARY_COLUMNS
    assert len(df) == 2
    a = df[df.provider == "anthropic"].iloc[0]
    assert a.calls == 5 and a.errors == 1
    assert a.error_rate == pytest.approx(0.2)
    assert a.total_cost_usd == pytest.approx(0.0009)
    assert a.cost_per_1k_calls_usd == pytest.approx(0.0009 / 5 * 1000)
    assert a.p50_latency_ms == pytest.approx(300)
    assert a.p95_latency_ms == pytest.approx(880)
    assert a.avg_input_tokens == pytest.approx(1000)
    o = df[df.provider == "ollama"].iloc[0]
    assert o.calls == 1 and o.total_cost_usd == 0


def test_cost_latency_summary_since_and_empty(tmp_db):
    from vsia.observability import SUMMARY_COLUMNS, cost_latency_summary

    assert cost_latency_summary().empty
    assert list(cost_latency_summary().columns) == SUMMARY_COLUMNS
    old = _utc_naive() - timedelta(days=30)
    with tmp_db.engine().begin() as conn:
        conn.execute(insert(tmp_db.llm_calls).values(provider="anthropic", model="m", purpose="triage",
                                                     input_tokens=1, output_tokens=1, cost_usd=1.0,
                                                     latency_ms=1, ok=True, created_at=old))
    _log(tmp_db, model="m")
    assert cost_latency_summary().iloc[0].calls == 2
    recent = cost_latency_summary(since=_utc_naive() - timedelta(days=1))
    assert recent.iloc[0].calls == 1


def test_cost_per_1000(tmp_db):
    from vsia.observability import cost_per_1000

    assert cost_per_1000("anthropic", "test-model") is None
    _log(tmp_db, cost_usd=0.0002)
    _log(tmp_db, cost_usd=0.0004)
    _log(tmp_db, cost_usd=1.0, purpose="chat")
    assert cost_per_1000("anthropic", "test-model", "triage") == pytest.approx(0.3)
    assert cost_per_1000("anthropic", "test-model", "chat") == pytest.approx(1000.0)


def test_timed_logs_genai_attributes_and_scrubs_text(caplog):
    from vsia.observability import timed

    caplog.set_level(logging.INFO, logger="vsia.observability")
    with timed("retrieval", **{"gen_ai.data_source.id": "recalls", "gen_ai.retrieval.top_k": 5,
                               "gen_ai.retrieval.query.text": "my VIN 1HGCM82633A004352"}) as span:
        span["vsia.note"] = "call me at (555) 123-4567"
    rec = caplog.records[-1]
    attrs = rec.vsia_span
    assert attrs["gen_ai.operation.name"] == "retrieval"
    assert attrs["gen_ai.data_source.id"] == "recalls" and attrs["gen_ai.retrieval.top_k"] == 5
    assert attrs["status"] == "ok" and attrs["duration_ms"] >= 0
    assert attrs["gen_ai.retrieval.query.text"] == "[omitted]"
    assert attrs["vsia.note"] == "call me at [PHONE]"
    assert "004352" not in rec.getMessage() and "123-4567" not in rec.getMessage()


def test_timed_records_errors_and_reraises(caplog):
    from vsia.observability import timed

    caplog.set_level(logging.INFO, logger="vsia.observability")
    with pytest.raises(ValueError), timed("tool_call", **{"gen_ai.tool.name": "recall_lookup"}):
        raise ValueError("bad")
    attrs = caplog.records[-1].vsia_span
    assert attrs["status"] == "error" and attrs["error.type"] == "ValueError"
    assert attrs["gen_ai.tool.name"] == "recall_lookup"


def test_llm_call_attributes_mapping():
    from vsia.observability import llm_call_attributes

    call = LLMCall(provider="openai", model="gpt-6-luna", purpose="triage", input_tokens=10,
                   output_tokens=5, cost_usd=0.1, latency_ms=50, ok=False, prompt_version="v2")
    a = llm_call_attributes(call)
    assert a["gen_ai.provider.name"] == "openai" and a["gen_ai.system"] == "openai"
    assert a["gen_ai.request.model"] == "gpt-6-luna"
    assert a["gen_ai.usage.input_tokens"] == 10 and a["gen_ai.usage.output_tokens"] == 5
    assert a["status"] == "error"


def test_complete_json_failure_records_no_model_output(tmp_db, monkeypatch):
    from vsia import llm

    marker = "MODEL-OUTPUT-7731"
    bad = {**VALID_TRIAGE, "severity": marker, "component": marker}
    seen: list[dict] = []
    monkeypatch.setitem(llm._PROVIDERS, "ollama", _fake_provider([json.dumps(bad), json.dumps(bad)], seen))
    with pytest.raises(llm.LLMError) as exc:
        llm.complete_json("sys", "user", TriageOutput, purpose="triage", provider="ollama", model="m")
    error = _rows(tmp_db)[0]["error"]
    assert "severity" in error
    assert marker not in error and "input_value" not in error
    assert marker not in str(exc.value)
