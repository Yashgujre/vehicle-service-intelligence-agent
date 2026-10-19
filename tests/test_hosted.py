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
    for k in ("GEMINI_API_KEY", "GROQ_API_KEY", "VSIA_EMBED_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
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
    with pytest.raises(ValueError, match="checksum"):
        bundle.ensure("https://example.test/b.tar.gz", "0" * 64, root=dst)
    info = bundle.ensure("https://example.test/b.tar.gz", m["sha256"], root=dst)
    assert info["sha256"] == m["sha256"] and bundle.installed(dst)
    con = sqlite3.connect(dst / "data" / bundle.DB_NAME)
    texts = [r[0] for r in con.execute("select summary from complaints order by odi_number")]
    con.close()
    assert "555-201-7788" not in texts[0] and texts[1] == "brakes failed"


def test_bundle_rejects_paths_outside_data(tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("../evil.txt")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    buf.seek(0)
    with tarfile.open(fileobj=buf, mode="r:gz") as tar, pytest.raises(ValueError, match="unsafe"):
        bundle._safe_members(tar)
