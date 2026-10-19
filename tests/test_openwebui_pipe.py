"""Open WebUI pipe: formatting, events and error handling, with httpx mocked (no network)."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

PIPE_FILE = Path(__file__).resolve().parents[1] / "openwebui" / "vsia_pipe.py"
spec = importlib.util.spec_from_file_location("vsia_pipe", PIPE_FILE)
vsia_pipe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vsia_pipe)


def make_pipe(handler, bearer: str = "secret") -> tuple[object, list]:
    """Pipe whose httpx.AsyncClient uses a MockTransport; returns the pipe and the captured requests."""
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    real = httpx.AsyncClient

    class MockClient(real):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(recording)
            super().__init__(*args, **kwargs)

    pipe = vsia_pipe.Pipe()
    pipe.valves.N8N_BEARER = bearer
    vsia_pipe.httpx.AsyncClient = MockClient
    return pipe, seen


@pytest.fixture(autouse=True)
def restore_client():
    real = httpx.AsyncClient
    yield
    vsia_pipe.httpx.AsyncClient = real


def run(pipe, body, user=None, events=None):
    async def emit(e):
        events.append(e)
    return asyncio.run(pipe.pipe(body, __user__=user or {"id": "u1"},
                                 __event_emitter__=emit if events is not None else None))


BODY = {"model": "vsia.vsia", "messages": [{"role": "user", "content": "Any brake recalls for the 2022 Mach-E?"}]}


def test_pipes_manifest():
    assert vsia_pipe.Pipe().pipes() == [{"id": "vsia", "name": "Vehicle Service Intelligence"}]


def test_answer_with_sources_and_events():
    reply = {"answer": "One recall covers the contactor.", "refused": False,
             "citations": ["recall:22V412000", "complaint:11770375"]}
    pipe, seen = make_pipe(lambda r: httpx.Response(200, json=reply))
    events: list = []
    out = run(pipe, BODY, events=events)

    assert out.startswith("One recall covers the contactor.")
    assert "**Sources**" in out
    assert "1. [NHTSA recall 22V412000](https://www.nhtsa.gov/recalls?nhtsaId=22V412000)" in out
    assert "2. NHTSA complaint ODI 11770375" in out
    assert "http" not in out.split("2. ")[1]

    req = seen[0]
    assert str(req.url) == "http://n8n:5678/webhook/vsia-chat"
    assert req.headers["authorization"] == "Bearer secret"
    sent = json.loads(req.content)
    assert sent["question"] == "Any brake recalls for the 2022 Mach-E?"
    assert sent["user_id"] == "u1" and sent["messages"] == BODY["messages"]

    kinds = [e["type"] for e in events]
    assert kinds[0] == "status" and kinds[-1] == "status"
    assert events[-1]["data"]["done"] is True
    sources = [e["data"] for e in events if e["type"] == "source"]
    assert len(sources) == 2
    assert sources[0]["source"] == {"name": "NHTSA recall 22V412000", "id": "22V412000"}
    assert sources[0]["metadata"][0]["url"] == "https://www.nhtsa.gov/recalls?nhtsaId=22V412000"
    assert "url" not in sources[1]["metadata"][0]


def test_refused_has_no_sources():
    reply = {"answer": "I can only answer questions about vehicle defects.", "citations": [], "refused": True}
    pipe, _ = make_pipe(lambda r: httpx.Response(200, json=reply))
    events: list = []
    out = run(pipe, BODY, events=events)
    assert out == "I can only answer questions about vehicle defects."
    assert not [e for e in events if e["type"] == "source"]


def test_no_bearer_sends_no_auth_header():
    pipe, seen = make_pipe(lambda r: httpx.Response(200, json={"answer": "ok", "citations": []}), bearer="")
    run(pipe, BODY)
    assert "authorization" not in seen[0].headers


def test_upstream_error_returns_message_not_exception():
    pipe, _ = make_pipe(lambda r: httpx.Response(500, text="boom"))
    events: list = []
    out = run(pipe, BODY, events=events)
    assert "unavailable" in out
    assert events[-1]["data"]["done"] is True


def test_n8n_fallback_body_on_502_is_shown():
    reply = {"answer": "The vehicle defect assistant is unavailable right now.", "citations": [], "error": True}
    pipe, _ = make_pipe(lambda r: httpx.Response(502, json=reply))
    assert run(pipe, BODY) == reply["answer"]


def test_empty_question_short_circuits():
    pipe, seen = make_pipe(lambda r: httpx.Response(200, json={}))
    out = run(pipe, {"messages": [{"role": "user", "content": "   "}]})
    assert "Please ask" in out and not seen


def test_works_without_event_emitter():
    pipe, _ = make_pipe(lambda r: httpx.Response(200, json={"answer": "ok", "citations": ["recall:23V168000"]}))
    assert "NHTSA recall 23V168000" in run(pipe, BODY, events=None)


def test_parse_citation_unknown_format():
    assert vsia_pipe.parse_citation("doc:abc")["url"] is None
    assert vsia_pipe.parse_citation("recall:BADID")["kind"] == "other"
