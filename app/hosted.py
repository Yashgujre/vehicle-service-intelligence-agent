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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
import streamlit as st
from sqlalchemy import func, select

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


def hosted_calls_today(provider: str) -> int:
    """Calls since midnight Pacific, ignoring calls made locally before the bundle was built and installed."""
    since = max(filter(None, [_pacific_midnight_utc(), _bundle_installed_utc()]))
    c = db.llm_calls.c
    q = select(func.count()).select_from(db.llm_calls).where(c.provider == provider, c.created_at >= since)
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
    if hosted_calls_today(choice.provider) + calls_needed > cap:
        return ("The shared free key has reached today's limit. Paste your own free key in the sidebar, or switch "
                "to the offline classifier. The limit resets at midnight Pacific time.")
    return None


def count_ai_calls(choice: ModelChoice, n: int) -> None:
    if choice.source == "hosted":
        st.session_state["ai_runs"] = st.session_state.get("ai_runs", 0) + n


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
        pick = st.radio("AI model", labels, key="model_pick", label_visibility="collapsed")
        _, provider, source = options[labels.index(pick)]
        keys: dict[str, str] = {}
        if source == "own":
            provider = st.selectbox("Provider", ["gemini", "groq", "openai", "anthropic"],
                                    format_func=lambda p: PROVIDER_LABELS[p], key="own_provider")
            name, url = FREE_KEY_LINKS[provider]
            key = st.text_input("API key", type="password", key=f"own_key_{provider}",
                                help="Used only for your requests in this browser session. Never stored or logged.")
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
