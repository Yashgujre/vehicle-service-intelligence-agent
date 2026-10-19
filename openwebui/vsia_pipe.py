"""
title: Vehicle Service Intelligence
author: VSIA project
version: 0.1.0
description: Answers questions about NHTSA vehicle defect complaints and recalls with cited sources, by calling the VSIA chat workflow in n8n (POST /webhook/vsia-chat).
requirements: httpx
"""

# Open WebUI Pipe function (interface verified in docs/research/02_technical_verification.md section 3.2).
# Non-streaming by default: whether n8n's Webhook / Respond to Webhook pair streams end to end is
# unverified, so the pipe waits for one JSON body {answer, citations, refused} (ADR-0076).

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from pydantic import BaseModel, Field

EventEmitter = Callable[[dict], Awaitable[None]] | None

RECALL_URL = "https://www.nhtsa.gov/recalls?nhtsaId={campaign}"
_RECALL = re.compile(r"^\d{2}[VEITC]\d{6}$")


def parse_citation(citation: str) -> dict[str, Any]:
    """Turn an API citation id ('recall:22V412000', 'complaint:11770375') into display fields.

    Recalls get a public nhtsa.gov link. Complaints have no stable public deep link, so only the ODI
    number is shown.
    """
    kind, _, ident = str(citation).partition(":")
    kind, ident = kind.strip().lower(), ident.strip()
    if kind == "recall" and _RECALL.match(ident):
        return {"kind": "recall", "id": ident, "label": f"NHTSA recall {ident}",
                "url": RECALL_URL.format(campaign=ident)}
    if kind == "complaint" and ident.isdigit():
        return {"kind": "complaint", "id": ident, "label": f"NHTSA complaint ODI {ident}", "url": None}
    return {"kind": "other", "id": str(citation), "label": str(citation), "url": None}


def render_answer(data: dict[str, Any]) -> str:
    """Markdown shown in the chat: the answer, then a numbered Sources list."""
    answer = str(data.get("answer") or "").strip() or "No answer was returned."
    citations = [parse_citation(c) for c in data.get("citations") or []]
    if data.get("refused") or not citations:
        return answer
    lines = [answer, "", "**Sources**", ""]
    for i, c in enumerate(citations, 1):
        lines.append(f"{i}. [{c['label']}]({c['url']})" if c["url"] else f"{i}. {c['label']}")
    return "\n".join(lines)


def source_event(citation: str) -> dict[str, Any]:
    """One Open WebUI `source` event per citation, so the UI shows citation chips."""
    c = parse_citation(citation)
    meta: dict[str, Any] = {"source": c["url"] or c["label"], "name": c["label"]}
    if c["url"]:
        meta["url"] = c["url"]
    return {"type": "source", "data": {"source": {"name": c["label"], "id": c["id"]},
                                       "document": [c["label"]], "metadata": [meta]}}


class Pipe:
    class Valves(BaseModel):
        N8N_WEBHOOK_URL: str = Field(default="http://n8n:5678/webhook/vsia-chat",
                                     description="n8n production webhook of workflow 04 (internal Docker URL)")
        N8N_BEARER: str = Field(default="", description="Value after 'Bearer ' in the n8n webhook header auth")
        TIMEOUT_S: int = Field(default=120, description="Seconds to wait for the answer")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self) -> list[dict[str, str]]:
        return [{"id": "vsia", "name": "Vehicle Service Intelligence"}]

    async def _status(self, emitter: EventEmitter, description: str, done: bool) -> None:
        if emitter:
            await emitter({"type": "status", "data": {"description": description, "done": done}})

    async def pipe(self, body: dict, __user__: dict | None = None, __event_emitter__: EventEmitter = None) -> str:
        messages = body.get("messages") or []
        question = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                content = m.get("content")
                if isinstance(content, list):  # multimodal message parts
                    content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
                question = str(content or "").strip()
                break
        if not question:
            return "Please ask a question about vehicle defect complaints or recalls."

        await self._status(__event_emitter__, "Searching complaints and recalls", False)
        headers = {"Authorization": f"Bearer {self.valves.N8N_BEARER}"} if self.valves.N8N_BEARER else {}
        payload = {"question": question, "messages": messages, "user_id": (__user__ or {}).get("id")}
        try:
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_S) as client:
                r = await client.post(self.valves.N8N_WEBHOOK_URL, json=payload, headers=headers)
            data = r.json() if r.content else {}
            if r.status_code >= 400 and not data.get("answer"):
                r.raise_for_status()
        except (httpx.HTTPError, ValueError) as e:
            await self._status(__event_emitter__, "The assistant is unavailable", True)
            return f"The vehicle defect assistant is unavailable right now ({type(e).__name__}). Please try again later."

        if __event_emitter__ and not data.get("refused"):
            for c in data.get("citations") or []:
                await __event_emitter__(source_event(c))
        await self._status(__event_emitter__, "Done", True)
        return render_answer(data)
