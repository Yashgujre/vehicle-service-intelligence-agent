"""Hosted demo support (ADR-0088, ADR-0089, ADR-0091): data bundle bootstrap, the AI model picker and the
quota guard for the host's free-tier key.

Model options, in the order the picker offers them:
  hosted   a free-tier key the host stored in secrets (GEMINI_API_KEY, GROQ_API_KEY); capped per day
  own key  the visitor pastes their own key; kept in this browser session only, never stored or logged
  ollama   local Ollama, only when one is reachable (development)
  offline  the TF-IDF baseline classifier; no AI call, always available
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
import streamlit as st
from sqlalchemy import func, or_, select

from vsia import bundle, config, db, llm

SESSION_AI_RUNS = 15  # AI calls one visitor session may make with the host's key
FREE_KEY_LINKS = {
    "gemini": ("Google AI Studio", "https://aistudio.google.com/apikey"),
    "groq": ("GroqCloud console", "https://console.groq.com/keys"),
    "openai": ("OpenAI platform (paid)", "https://platform.openai.com/api-keys"),
    "anthropic": ("Anthropic console (paid)", "https://console.anthropic.com/settings/keys"),
}
PROVIDER_LABELS = {"gemini": "Google Gemini", "groq": "Groq", "openai": "OpenAI", "anthropic": "Anthropic Claude",
                   "ollama": "Ollama (local)", "heuristic": "Offline classifier"}


@st.cache_resource(show_spinner="First start: downloading the demo dataset (about a minute)...")
def _install_bundle(url: str, sha256: str | None) -> str | None:
    """One attempt per server process; returns the error text, or None on success."""
    try:
        bundle.ensure(url, sha256)
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"[:300]
    db.engine.cache_clear()
    return None


def bootstrap() -> None:
    """Fetch the demo data bundle on first start when VSIA_BUNDLE_URL is set and data/ is empty. A hosted
    container has no Ollama, so it embeds queries in-process (same model, same vectors). If the download or
    checksum fails, no database file exists and the pages fall back to the read-only snapshot."""
    url = os.getenv("VSIA_BUNDLE_URL")
    if not url:
        return
    if not os.getenv("VSIA_EMBED_PROVIDER"):
        os.environ["VSIA_EMBED_PROVIDER"] = "fastembed"
        config.env.cache_clear()
    sha256 = os.getenv("VSIA_BUNDLE_SHA256") or None
    if bundle.installed(sha256=sha256):
        return
    if err := _install_bundle(url, sha256):
        st.warning("The demo dataset could not be installed, so this app is showing the read-only snapshot "
                   f"and the agent is unavailable. Cause: {err}")


@st.cache_data(ttl=60, show_spinner=False)
def _ollama_up() -> bool:
    base = config.env().ollama_base_url or config.settings()["llm"]["providers"]["ollama"]["base_url"]
    try:
        return httpx.get(f"{base}/api/tags", timeout=0.5).status_code == 200
    except httpx.HTTPError:
        return False


@dataclass
class ModelChoice:
    provider: str
    model: str
    source: str  # hosted | own | local | offline
    keys: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{PROVIDER_LABELS.get(self.provider, self.provider)} ({self.model})"

    @property
    def uses_ai(self) -> bool:
        return self.provider != "heuristic"


def _pacific_midnight_utc() -> datetime:
    """Gemini free-tier daily quotas reset at midnight Pacific time."""
    now = datetime.now(ZoneInfo("America/Los_Angeles"))
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)


def _bundle_installed_utc() -> datetime | None:
    try:
        info = json.loads((config.REPO_ROOT / bundle.MARKER).read_text())
        return datetime.fromisoformat(info["installed_at"]).astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:  # noqa: BLE001
        return None


def hosted_calls_today(provider: str, model: str | None = None) -> int:
    """Calls since midnight Pacific that used quota, ignoring calls made locally before the bundle was built and
    installed. Rate-limited calls (HTTP 429) do not use quota."""
    since = max(filter(None, [_pacific_midnight_utc(), _bundle_installed_utc()]))
    c = db.llm_calls.c
    q = select(func.count()).select_from(db.llm_calls).where(
        c.provider == provider, c.created_at >= since, or_(c.ok.is_(True), c.error.is_(None), ~c.error.contains("429")))
    if model:
        q = q.where(c.model == model)
    try:
        with db.engine().connect() as conn:
            return int(conn.execute(q).scalar_one())
    except Exception:  # noqa: BLE001
        return 0


def quota_block(choice: ModelChoice, calls_needed: int = 1) -> str | None:
    """Reason this request may not use the host's key, or None if it may."""
    if choice.source != "hosted":
        return None
    used = st.session_state.get("ai_runs", 0)
    if used + calls_needed > SESSION_AI_RUNS:
        return (f"This session has used its {SESSION_AI_RUNS} free AI calls on the shared key. Paste your own free "
                "key in the sidebar, or switch to the offline classifier.")
    cap = config.env().vsia_hosted_daily_llm_calls
    if hosted_calls_today(choice.provider, choice.model) + calls_needed > cap:
        return ("The shared free key has reached today's limit. Paste your own free key in the sidebar, or switch "
                "to the offline classifier. The limit resets at midnight Pacific time.")
    return None


def count_ai_calls(choice: ModelChoice, n: int) -> None:
    if choice.source == "hosted":
        st.session_state["ai_runs"] = st.session_state.get("ai_runs", 0) + n


# Shared by every session in this server process: a model that just failed is skipped for a while, so visitors
# do not each wait on a model whose daily quota is spent or that is overloaded.
_RATE_LIMITED: dict[tuple[str, str], float] = {}
RATE_LIMIT_SKIP_S = 600
OVERLOAD_SKIP_S = 120
_TRANSPORT_ERRORS = ("Timeout", "ConnectError", "RemoteProtocolError", "ReadError")


def unavailable(status: int | None, error: str | None) -> bool:
    """The provider refused or could not serve the call (rate limit, overload, no response): the next model in
    the chain may succeed. Invalid output and other errors are not retried on another model."""
    return status == 429 or (status or 0) >= 500 or any(s in str(error or "") for s in _TRANSPORT_ERRORS)


def mark_unavailable(choice: ModelChoice, status: int | None) -> None:
    if choice.source == "hosted":
        skip = RATE_LIMIT_SKIP_S if status == 429 else OVERLOAD_SKIP_S
        _RATE_LIMITED[(choice.provider, choice.model)] = time.monotonic() + skip


def candidates(choice: ModelChoice, calls_needed: int = 1) -> tuple[list[ModelChoice], str | None]:
    """Models to try in order for this request, and the reason to refuse if there are none. On the host's key:
    the chosen model, then the provider's backup models (separate free-tier quotas), then Groq if its key is set.
    Visitor keys and local or offline models are used as chosen."""
    if choice.source != "hosted":
        return [choice], None
    if block := quota_block(choice, calls_needed):
        if "this session" in block:
            return [], block
    chain = [choice] + [ModelChoice(provider=choice.provider, model=m, source="hosted")
                        for m in config.settings()["llm"]["providers"][choice.provider].get("backup_models", [])]
    if choice.provider != "groq" and llm.api_key("groq"):
        chain.append(ModelChoice(provider="groq", model=config.llm_model("groq"), source="hosted"))
    now = time.monotonic()
    usable = [c for c in chain if not quota_block(c, calls_needed)]
    fresh = [c for c in usable if _RATE_LIMITED.get((c.provider, c.model), 0) <= now]
    if not usable:
        return [], quota_block(choice, calls_needed)
    return fresh or usable[-1:], None


def model_picker() -> ModelChoice:
    """Sidebar control shared by the interactive pages."""
    providers = config.settings()["llm"]["providers"]
    options: list[tuple[str, str, str]] = []  # (label, provider, source)
    for p in ("gemini", "groq"):
        if llm.api_key(p):
            options.append((f"{PROVIDER_LABELS[p]}, free (shared key)", p, "hosted"))
    for p in ("anthropic", "openai"):
        if llm.api_key(p):
            options.append((f"{PROVIDER_LABELS[p]} (host key)", p, "hosted"))
    if _ollama_up():
        options.append(("Ollama, local model", "ollama", "local"))
    options.append(("Use my own API key", "", "own"))
    options.append(("Offline classifier (no AI call)", "heuristic", "offline"))

    with st.sidebar:
        st.markdown("**AI model**")
        labels = [o[0] for o in options]
        # Streamlit drops a widget's state when another page is shown, so the choice is kept under a second key.
        saved = st.session_state.get("model_pick_saved")
        pick = st.radio("AI model", labels, index=labels.index(saved) if saved in labels else 0, key="model_pick",
                        label_visibility="collapsed")
        st.session_state["model_pick_saved"] = pick
        _, provider, source = options[labels.index(pick)]
        keys: dict[str, str] = {}
        if source == "own":
            own = ["gemini", "groq", "openai", "anthropic"]
            saved_p = st.session_state.get("own_provider_saved")
            provider = st.selectbox("Provider", own, index=own.index(saved_p) if saved_p in own else 0,
                                    format_func=lambda p: PROVIDER_LABELS[p], key="own_provider")
            st.session_state["own_provider_saved"] = provider
            name, url = FREE_KEY_LINKS[provider]
            key = st.text_input("API key", type="password", key=f"own_key_{provider}",
                                value=st.session_state.get(f"own_key_saved_{provider}", ""),
                                help="Used only for your requests in this browser session. Never stored or logged.")
            st.session_state[f"own_key_saved_{provider}"] = key
            st.caption(f"Get a key: [{name}]({url}). Gemini and Groq have free tiers; no card needed.")
            if key:
                keys[provider] = key.strip()
            else:
                st.caption("No key entered yet: AI requests will fall back to the offline classifier.")
                provider, source = "heuristic", "offline"
        elif source == "hosted":
            left = max(0, SESSION_AI_RUNS - st.session_state.get("ai_runs", 0))
            st.caption(f"Shared free-tier key: {left} AI calls left in this session.")
        elif source == "offline":
            st.caption("Runs the same workflow with the TF-IDF baseline classifier: no AI call, instant.")
        model = providers.get(provider, {}).get("model", provider)
    return ModelChoice(provider=provider, model=model, source=source, keys=keys)


def quota_hit(signals: dict) -> bool:
    return signals.get("llm_status") == 429 or "429" in str(signals.get("llm_error", ""))
