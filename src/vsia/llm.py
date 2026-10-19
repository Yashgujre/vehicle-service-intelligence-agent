"""LLM gateway (FR-6, FR-11). One function, `complete_json`, hides the provider. Switching between
Claude, OpenAI, Gemini, Groq and a local Ollama model is a config change (VSIA_LLM_PROVIDER /
VSIA_LLM_MODEL). Gemini and Groq are called through their OpenAI-compatible Chat Completions endpoints
(ADR-0088).

Every call:
  1. asks the provider for JSON constrained by the Pydantic model's schema (native structured output),
  2. validates the reply with Pydantic, and retries once with the validation error if it fails,
  3. logs provider, model, tokens, cost and latency to llm_calls (never the prompt text).

API keys come from the environment, or from `use_keys()` for one request: the hosted demo uses it for a
visitor's own key, which is never stored or logged.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from vsia import config
from vsia.db import log_llm_call
from vsia.schemas import LLMCall

T = TypeVar("T", bound=BaseModel)

# Keywords some providers reject in structured-output schemas. Pydantic re-checks them after the call.
_STRIP_KEYS = {"default", "title", "minimum", "maximum", "maxItems", "minItems", "pattern",
               "exclusiveMinimum", "exclusiveMaximum", "maxLength", "minLength"}


class LLMError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status  # HTTP status of the provider error, if any (429 = rate limit or quota)


# Provider -> environment variable holding its key. Ollama and the heuristic baseline need none.
KEY_ENV = {"anthropic": "anthropic_api_key", "openai": "openai_api_key", "gemini": "gemini_api_key",
           "groq": "groq_api_key"}

_key_override: ContextVar[dict[str, str]] = ContextVar("vsia_llm_keys", default={})


@contextmanager
def use_keys(keys: dict[str, str]) -> Iterator[None]:
    """Use these API keys (provider -> key) for calls made inside the block, ahead of the environment."""
    token = _key_override.set({**_key_override.get(), **{k: v for k, v in keys.items() if v}})
    try:
        yield
    finally:
        _key_override.reset(token)


def api_key(provider: str) -> str | None:
    if provider in _key_override.get():
        return _key_override.get()[provider]
    attr = KEY_ENV.get(provider)
    return (getattr(config.env(), attr, None) or None) if attr else None


def needs_key(provider: str) -> bool:
    return provider in KEY_ENV


@dataclass
class LLMResult:
    data: BaseModel
    call: LLMCall
    raw_text: str
    attempts: int = 1


def price(provider: str, input_tokens: int, output_tokens: int) -> float:
    p = config.settings()["llm"]["providers"].get(provider, {}).get("price_per_mtok", {})
    return round(input_tokens / 1e6 * p.get("input", 0) + output_tokens / 1e6 * p.get("output", 0), 8)


def provider_schema(model: type[BaseModel], strict: bool = False) -> dict:
    """Pydantic JSON schema cleaned for provider structured-output modes. In strict mode (OpenAI) every
    object lists all its properties as required and forbids extra keys."""
    schema = copy.deepcopy(model.model_json_schema())

    def walk(node):
        if isinstance(node, dict):
            for k in list(node):
                if k in _STRIP_KEYS:
                    node.pop(k)
            if node.get("type") == "object" or "properties" in node:
                node["additionalProperties"] = False
                if strict and "properties" in node:
                    node["required"] = list(node["properties"].keys())
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    return schema


def inline_refs(schema: dict) -> dict:
    """Replace every {"$ref": "#/$defs/X"} with the definition itself and drop $defs. Some OpenAI-compatible
    endpoints accept only self-contained schemas."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                target = copy.deepcopy(defs[ref.split("/")[-1]])
                extra = {k: v for k, v in node.items() if k != "$ref"}
                return walk({**target, **extra})
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (408, 409, 429) or exc.response.status_code >= 500
    return isinstance(exc, (httpx.TransportError,))


_retry = retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=15),
               retry=retry_if_exception(_retryable), reraise=True)


@_retry
def _call_ollama(model: str, system: str, user: str, schema: dict, max_tokens: int, temperature: float):
    base = config.env().ollama_base_url or config.settings()["llm"]["providers"]["ollama"]["base_url"]
    r = httpx.post(f"{base}/api/chat", timeout=300.0, json={
        "model": model, "stream": False, "format": schema,
        "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": 4096},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    })
    r.raise_for_status()
    d = r.json()
    return d["message"]["content"], int(d.get("prompt_eval_count", 0)), int(d.get("eval_count", 0))


@_retry
def _call_anthropic(model: str, system: str, user: str, schema: dict, max_tokens: int, temperature: float):
    key = api_key("anthropic")
    if not key:
        raise LLMError("ANTHROPIC_API_KEY is not set")
    r = httpx.post("https://api.anthropic.com/v1/messages", timeout=120.0,
                   headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                   json={"model": model, "max_tokens": max_tokens, "temperature": temperature, "system": system,
                         "messages": [{"role": "user", "content": user}],
                         "output_config": {"format": {"type": "json_schema", "schema": schema}}})
    r.raise_for_status()
    d = r.json()
    text = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
    u = d.get("usage", {})
    return text, int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))


@_retry
def _call_openai(model: str, system: str, user: str, schema: dict, max_tokens: int, temperature: float):
    key = api_key("openai")
    if not key:
        raise LLMError("OPENAI_API_KEY is not set")
    r = httpx.post("https://api.openai.com/v1/responses", timeout=120.0,
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": model, "max_output_tokens": max_tokens,
                         "input": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                         "text": {"format": {"type": "json_schema", "name": "output", "strict": True,
                                             "schema": schema}}})
    r.raise_for_status()
    d = r.json()
    text = d.get("output_text") or "".join(
        c.get("text", "") for item in d.get("output", []) for c in item.get("content", []) or []
        if c.get("type") in ("output_text", "text"))
    u = d.get("usage", {})
    return text, int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))


def _chat_completions(provider: str):
    """Caller for an OpenAI-compatible /chat/completions endpoint (Gemini, Groq). base_url and optional
    extra request fields (for example reasoning_effort) come from config llm.providers.<provider>."""

    @_retry
    def call(model: str, system: str, user: str, schema: dict, max_tokens: int, temperature: float):
        key = api_key(provider)
        if not key:
            raise LLMError(f"{KEY_ENV[provider].upper()} is not set")
        pcfg = config.settings()["llm"]["providers"][provider]
        r = httpx.post(f"{pcfg['base_url'].rstrip('/')}/chat/completions", timeout=120.0,
                       headers={"Authorization": f"Bearer {key}"},
                       json={"model": model, "max_tokens": max_tokens, "temperature": temperature,
                             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                             "response_format": {"type": "json_schema", "json_schema": {
                                 "name": "output", "strict": True, "schema": inline_refs(schema)}},
                             **pcfg.get("extra_body", {})})
        r.raise_for_status()
        d = r.json()
        text = (d.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        u = d.get("usage") or {}
        return text, int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0))

    return call


_PROVIDERS = {"ollama": _call_ollama, "anthropic": _call_anthropic, "openai": _call_openai,
              "gemini": _chat_completions("gemini"), "groq": _chat_completions("groq")}


def complete_json(system: str, user: str, output_model: type[T], *, purpose: str,
                  provider: str | None = None, model: str | None = None, prompt_version: str | None = None,
                  ref_id: str | None = None, max_tokens: int | None = None) -> LLMResult:
    provider = provider or config.llm_provider()
    model = model or config.llm_model(provider)
    if provider not in _PROVIDERS:
        raise LLMError(f"unknown or non-LLM provider: {provider}")
    cfg = config.settings()["llm"]
    max_tokens = max_tokens or cfg["max_output_tokens"]
    schema = provider_schema(output_model, strict=provider in ("openai", "gemini", "groq"))
    fn = _PROVIDERS[provider]

    total_in = total_out = 0
    started = time.perf_counter()
    msg = user
    last_err: str | None = None
    status: int | None = None
    for attempt in range(2):
        try:
            text, tin, tout = fn(model, system, msg, schema, max_tokens, cfg["temperature"])
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            if isinstance(e, httpx.HTTPStatusError):
                status = e.response.status_code
            break
        total_in += tin
        total_out += tout
        try:
            data = output_model.model_validate(json.loads(text))
            call = LLMCall(provider=provider, model=model, purpose=purpose, input_tokens=total_in,
                           output_tokens=total_out, cost_usd=price(provider, total_in, total_out),
                           latency_ms=int((time.perf_counter() - started) * 1000), ok=True,
                           prompt_version=prompt_version, ref_id=ref_id)
            log_llm_call(call)
            return LLMResult(data=data, call=call, raw_text=text, attempts=attempt + 1)
        except (json.JSONDecodeError, ValidationError) as e:
            # Logged errors must not quote the model's reply (it can echo complaint text): field paths and
            # error types only. The full message is still fed back to the model for the repair retry.
            if isinstance(e, ValidationError):
                brief = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['type']}" for x in e.errors()[:8])
            else:
                brief = f"JSONDecodeError at position {e.pos}"
            last_err = f"invalid output (attempt {attempt + 1}): {brief}"[:400]
            msg = (f"{user}\n\nYour previous reply was rejected by the validator:\n{str(e)[:800]}\n"
                   "Return only JSON that satisfies the schema.")
    call = LLMCall(provider=provider, model=model, purpose=purpose, input_tokens=total_in,
                   output_tokens=total_out, cost_usd=price(provider, total_in, total_out),
                   latency_ms=int((time.perf_counter() - started) * 1000), ok=False, error=last_err,
                   prompt_version=prompt_version, ref_id=ref_id)
    log_llm_call(call)
    raise LLMError(last_err or "LLM call failed", status=status)


@_retry
def embed_ollama(texts: list[str], model: str | None = None) -> list[list[float]]:
    base = config.env().ollama_base_url or config.settings()["llm"]["providers"]["ollama"]["base_url"]
    model = model or config.settings()["embeddings"]["providers"]["ollama"]["model"]
    r = httpx.post(f"{base}/api/embed", timeout=300.0, json={"model": model, "input": texts})
    r.raise_for_status()
    return r.json()["embeddings"]
