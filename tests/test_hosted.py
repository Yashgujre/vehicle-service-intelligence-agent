"""Tests for the hosted-demo additions: Gemini and Groq through the OpenAI-compatible gateway, per-request
API keys, the in-process embedder switch and the demo data bundle (ADR-0088 to ADR-0091). No network."""

from __future__ import annotations

import io
import json
import sqlite3
import tarfile
from contextlib import contextmanager

import httpx
import pytest

from vsia import bundle, config, llm, retrieval
from vsia.schemas import TriageOutput

VALID = {"extracted": {"symptom": "Car braked by itself"}, "component": "SERVICE BRAKES",
         "severity": "S2", "severity_reason": "unintended braking while moving", "model_confidence": 0.7}


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for k in ("GEMINI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.setenv(k, "")  # an empty variable also masks a real key in the developer's .env
    monkeypatch.delenv("VSIA_EMBED_PROVIDER", raising=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 't.db'}")
    from vsia import db

    config.env.cache_clear()
    db.engine.cache_clear()
    yield monkeypatch
    config.env.cache_clear()
    db.engine.cache_clear()


def _refs(node) -> bool:
    if isinstance(node, dict):
        return "$ref" in node or "$defs" in node or any(_refs(v) for v in node.values())
    if isinstance(node, list):
        return any(_refs(v) for v in node)
    return False


def test_inline_refs_makes_schema_self_contained():
    schema = llm.provider_schema(TriageOutput, strict=True)
    assert _refs(schema)
    flat = llm.inline_refs(schema)
    assert not _refs(flat)
    assert flat["properties"]["extracted"]["properties"]["symptom"]["type"] == "string"
    assert flat["properties"]["recall_matches"]["items"]["additionalProperties"] is False


def test_use_keys_overrides_environment_and_resets(clean_env):
    clean_env.setenv("GEMINI_API_KEY", "env-key")
    config.env.cache_clear()
    assert llm.api_key("gemini") == "env-key"
    with llm.use_keys({"gemini": "visitor-key", "groq": ""}):
        assert llm.api_key("gemini") == "visitor-key"
        assert llm.api_key("groq") is None
    assert llm.api_key("gemini") == "env-key"
    assert llm.api_key("ollama") is None and not llm.needs_key("ollama")


def test_gemini_call_uses_openai_compatible_request(clean_env):
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(url=url, headers=headers, body=json)
        body = {"choices": [{"message": {"content": __import__("json").dumps(VALID)}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 40}}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    clean_env.setattr(llm.httpx, "post", fake_post)
    with llm.use_keys({"gemini": "k-123"}):
        res = llm.complete_json("sys", "user", TriageOutput, purpose="test", provider="gemini")
    assert res.data.component == "SERVICE BRAKES"
    assert (res.call.input_tokens, res.call.output_tokens, res.call.cost_usd) == (120, 40, 0.0)
    assert seen["url"].startswith("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
    assert seen["headers"]["Authorization"] == "Bearer k-123"
    fmt = seen["body"]["response_format"]
    assert fmt["type"] == "json_schema" and not _refs(fmt["json_schema"]["schema"])


def test_groq_sends_configured_extra_body(clean_env):
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen.update(url=url, body=json)
        body = {"choices": [{"message": {"content": __import__("json").dumps(VALID)}}], "usage": {}}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    clean_env.setattr(llm.httpx, "post", fake_post)
    with llm.use_keys({"groq": "g"}):
        llm.complete_json("sys", "user", TriageOutput, purpose="test", provider="groq")
    assert seen["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert seen["body"]["reasoning_effort"] == "low"


def test_missing_key_and_rate_limit_raise_llm_error_with_status(clean_env):
    with pytest.raises(llm.LLMError, match="GEMINI_API_KEY"):
        llm.complete_json("s", "u", TriageOutput, purpose="test", provider="gemini")

    def limited(*a, **k):
        req = httpx.Request("POST", "https://example.test")
        raise httpx.HTTPStatusError("429 Too Many Requests", request=req, response=httpx.Response(429, request=req))

    clean_env.setitem(llm._PROVIDERS, "gemini", limited)
    with pytest.raises(llm.LLMError) as e:
        llm.complete_json("s", "u", TriageOutput, purpose="test", provider="gemini")
    assert e.value.status == 429


def test_embed_provider_switch(clean_env):
    assert retrieval._default_embedder() is retrieval._ollama_embedder
    clean_env.setenv("VSIA_EMBED_PROVIDER", "fastembed")
    config.env.cache_clear()
    assert retrieval._default_embedder() is retrieval._fastembed_embedder


def _fake_repo(root):
    data = root / "data"
    for p in bundle.BUNDLE_PATHS:
        f = root / p
        if p.endswith((".joblib", ".json")):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x")
        else:
            f.mkdir(parents=True, exist_ok=True)
            (f / "meta.jsonl").write_text("{}\n")
    (data / "models" / "routing_gemini.json").write_text(json.dumps({"threshold": 0.8}))
    con = sqlite3.connect(data / bundle.DB_NAME)
    con.execute("create table complaints (odi_number integer, summary text)")
    con.execute("insert into complaints values (1, 'call me at 555-201-7788 please')")
    con.execute("insert into complaints values (2, 'brakes failed')")
    con.commit()
    con.close()


def test_bundle_build_redacts_and_ensure_installs(tmp_path, monkeypatch):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _fake_repo(src)
    out = tmp_path / "b.tar.gz"
    m = bundle.build(out, root=src)
    assert m["complaints_redacted"] == 1
    assert "data/models/routing_gemini.json" in m["files"]
    payload = out.read_bytes()

    @contextmanager
    def fake_stream(method, url, follow_redirects=True, timeout=None):
        yield httpx.Response(200, content=payload, request=httpx.Request(method, url))

    monkeypatch.setattr(bundle.httpx, "stream", fake_stream)
    with pytest.raises(ValueError, match="VSIA_BUNDLE_SHA256"):
        bundle.ensure("https://example.test/b.tar.gz", None, root=dst)
    with pytest.raises(ValueError, match="checksum"):
        bundle.ensure("https://example.test/b.tar.gz", "0" * 64, root=dst)
    info = bundle.ensure("https://example.test/b.tar.gz", m["sha256"], root=dst)
    assert info["sha256"] == m["sha256"] and bundle.installed(dst)
    con = sqlite3.connect(dst / "data" / bundle.DB_NAME)
    texts = [r[0] for r in con.execute("select summary from complaints order by odi_number")]
    con.close()
    assert "555-201-7788" not in texts[0] and texts[1] == "brakes failed"

    assert bundle.installed(dst, m["sha256"]) and not bundle.installed(dst, "f" * 64)
    with pytest.raises(ValueError, match="checksum"):
        bundle.ensure("https://example.test/b.tar.gz", "f" * 64, root=dst)


def test_bundle_rejects_paths_outside_data(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("../evil.txt")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    buf.seek(0)
    with tarfile.open(fileobj=buf, mode="r:gz") as tar, pytest.raises(ValueError, match="unsafe"):
        bundle._safe_members(tar)


@pytest.fixture
def hosted_mod(clean_env):
    import sys
    from types import SimpleNamespace

    sys.path.insert(0, str(config.REPO_ROOT / "app"))
    import hosted

    session: dict = {}
    clean_env.setattr(hosted, "st", SimpleNamespace(session_state=session, warning=lambda msg: session.update(warned=msg)))
    return hosted, session


def _log_calls(provider: str, n: int) -> None:
    from datetime import datetime

    from sqlalchemy import insert

    from vsia import db

    with db.engine().begin() as conn:
        conn.execute(insert(db.llm_calls), [{"provider": provider, "model": "m", "purpose": "triage", "ok": True,
                                             "created_at": datetime.utcnow()} for _ in range(n)])


def test_quota_guard_caps_session_and_day_for_the_shared_key_only(hosted_mod, monkeypatch):
    hosted, session = hosted_mod
    shared = hosted.ModelChoice(provider="gemini", model="m", source="hosted")
    own = hosted.ModelChoice(provider="gemini", model="m", source="own", keys={"gemini": "k"})
    assert hosted.quota_block(shared) is None
    hosted.count_ai_calls(shared, hosted.SESSION_AI_RUNS - 1)
    hosted.count_ai_calls(own, 50)
    assert session["ai_runs"] == hosted.SESSION_AI_RUNS - 1
    assert hosted.quota_block(shared) is None
    assert "this session" in hosted.quota_block(shared, calls_needed=2).lower()
    assert hosted.quota_block(own, calls_needed=99) is None

    session.clear()
    monkeypatch.setattr(hosted, "_bundle_installed_utc", lambda: None)
    _log_calls("gemini", config.env().vsia_hosted_daily_llm_calls)
    assert "today's limit" in hosted.quota_block(shared)
    assert hosted.quota_block(hosted.ModelChoice(provider="groq", model="m", source="hosted")) is None


def test_daily_cap_ignores_calls_shipped_inside_the_bundle(hosted_mod, monkeypatch):
    from datetime import datetime, timedelta

    hosted, _ = hosted_mod
    shared = hosted.ModelChoice(provider="gemini", model="m", source="hosted")
    _log_calls("gemini", config.env().vsia_hosted_daily_llm_calls)
    monkeypatch.setattr(hosted, "_bundle_installed_utc", lambda: datetime.utcnow() + timedelta(seconds=1))
    assert hosted.hosted_calls_today("gemini") == 0
    assert hosted.quota_block(shared) is None


def test_candidates_move_to_backup_models_on_cap_or_rate_limit(hosted_mod, monkeypatch):
    from datetime import datetime

    from sqlalchemy import insert

    from vsia import db

    hosted, session = hosted_mod
    monkeypatch.setattr(hosted, "_bundle_installed_utc", lambda: None)
    monkeypatch.setattr(hosted, "_RATE_LIMITED", {})
    main = config.llm_model("gemini")
    backups = config.settings()["llm"]["providers"]["gemini"]["backup_models"]
    shared = hosted.ModelChoice(provider="gemini", model=main, source="hosted")

    chain, block = hosted.candidates(shared)
    assert block is None and [c.model for c in chain] == [main, *backups]

    hosted.mark_unavailable(shared, 429)
    chain, _ = hosted.candidates(shared)
    assert [c.model for c in chain] == backups

    monkeypatch.setattr(hosted, "_RATE_LIMITED", {})
    with db.engine().begin() as conn:
        conn.execute(insert(db.llm_calls), [{"provider": "gemini", "model": main, "purpose": "triage", "ok": True,
                                             "created_at": datetime.utcnow()}
                                            for _ in range(config.env().vsia_hosted_daily_llm_calls)])
        conn.execute(insert(db.llm_calls), [{"provider": "gemini", "model": backups[0], "purpose": "triage",
                                             "ok": False, "error": "HTTP 429 Too Many Requests",
                                             "created_at": datetime.utcnow()} for _ in range(5)])
    assert hosted.hosted_calls_today("gemini", backups[0]) == 0
    chain, _ = hosted.candidates(shared)
    assert [c.model for c in chain] == backups

    session["ai_runs"] = hosted.SESSION_AI_RUNS
    chain, block = hosted.candidates(shared)
    assert chain == [] and "this session" in block.lower()
    own = hosted.ModelChoice(provider="gemini", model=main, source="own", keys={"gemini": "k"})
    assert hosted.candidates(own) == ([own], None)


def test_unavailable_covers_rate_limits_overload_and_timeouts_only(hosted_mod):
    hosted, _ = hosted_mod
    assert hosted.unavailable(429, None) and hosted.unavailable(503, None)
    assert hosted.unavailable(None, "ReadTimeout: timed out")
    assert not hosted.unavailable(None, "invalid output (attempt 2): JSONDecodeError at position 3")
    assert not hosted.unavailable(400, "HTTPStatusError: 400 Bad Request")


def test_fail_fast_raises_overload_without_retrying(clean_env, monkeypatch):
    clean_env.setenv("GEMINI_API_KEY", "k")
    config.env.cache_clear()
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(timeout)
        return httpx.Response(503, json={"error": "busy"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    with llm.fail_fast(), pytest.raises(llm.LLMError) as e:
        llm.complete_json("s", "u", TriageOutput, purpose="test", provider="gemini")
    assert e.value.status == 503 and calls == [30.0]


def test_quota_hit_reads_status_or_error_text(hosted_mod):
    hosted, _ = hosted_mod
    assert hosted.quota_hit({"llm_status": 429})
    assert hosted.quota_hit({"llm_error": "HTTP 429 Too Many Requests"})
    assert not hosted.quota_hit({"llm_status": 500, "llm_error": "server error"})


def test_bootstrap_falls_back_to_snapshot_when_install_fails(hosted_mod, monkeypatch):
    hosted, session = hosted_mod
    monkeypatch.setenv("VSIA_BUNDLE_URL", "https://example.test/b.tar.gz")
    monkeypatch.setenv("VSIA_EMBED_PROVIDER", "")
    monkeypatch.delenv("VSIA_BUNDLE_SHA256", raising=False)
    monkeypatch.setattr(hosted.bundle, "installed", lambda root=None, sha256=None: False)
    hosted._install_bundle.clear()
    hosted.bootstrap()
    hosted._install_bundle.clear()
    assert "read-only snapshot" in session["warned"] and "VSIA_BUNDLE_SHA256" in session["warned"]
    assert config.env().vsia_embed_provider == "fastembed"


def test_rag_redacts_the_question_before_any_model_call(clean_env):
    from vsia import rag, retrieval

    prompts: list[str] = []

    def fake_complete_json(system, user, schema, **kw):
        prompts.append(user)
        data = (rag.QueryPlan(intent="lookup", search_text="battery") if schema is rag.QueryPlan
                else rag.ChatAnswer(answer="No context.", refused=True))
        return llm.LLMResult(data=data, call=None, raw_text="")

    def no_retrieval(*a, **kw):
        raise RuntimeError("offline")

    clean_env.setattr(rag.llm, "complete_json", fake_complete_json)
    clean_env.setattr(retrieval, "search_complaints", no_retrieval)
    rag.answer("I am Jane Doe, call 555-201-7788 or jane.doe@example.com: why does my 12V battery die?")
    assert len(prompts) == 2
    for p in prompts:
        assert "555-201-7788" not in p and "jane.doe@example.com" not in p and "battery" in p


def test_year_filter_matches_recall_documents_that_span_years():
    doc = {"campaign_number": "24V001000", "model_years": [2022, 2023, 2024]}
    assert retrieval.matches_filter(doc, {"model_years": 2023})
    assert retrieval.matches_filter(doc, {"model_years": "2023"})
    assert not retrieval.matches_filter(doc, {"model_years": 2021})
    assert not retrieval.matches_filter(doc, {"model_year": 2023})


def test_defang_md_blocks_links_and_images_but_keeps_formatting():
    import sys

    sys.path.insert(0, str(config.REPO_ROOT / "app"))
    import ui

    out = ui.defang_md("**Yes**: see [here](https://evil.example) ![x](https://evil.example/p.png) <b>")
    assert "](" not in out.replace("\\](", "").replace("\\(", "")
    assert "\\[here\\]" in out and "\\!\\[x\\]" in out and "\\<b\\>" in out
    assert out.startswith("**Yes**")
