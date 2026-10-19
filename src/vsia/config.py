"""Runtime configuration: secrets and switches from the environment, domain settings from YAML."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"


class Env(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_prefix="", extra="ignore")

    database_url: str = f"sqlite:///{DATA_DIR / 'vsia.db'}"
    vsia_settings_file: str = str(REPO_ROOT / "config" / "settings.yaml")
    vsia_llm_provider: str | None = None
    vsia_llm_model: str | None = None
    vsia_embed_provider: str | None = None
    vsia_vector_store: str = "local"  # local | pinecone
    vsia_confidence_threshold: float | None = None

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    pinecone_api_key: str | None = None
    pinecone_index: str = "vsia"
    llama_cloud_api_key: str | None = None
    ollama_base_url: str | None = None

    mlflow_tracking_uri: str = f"sqlite:///{DATA_DIR / 'mlflow.db'}"
    mlflow_artifact_root: str = str(DATA_DIR / "mlartifacts")

    # Hosted demo (ADR-0089, ADR-0091): data bundle to fetch when data/ is empty, and the daily cap on
    # LLM calls made with the host's own free-tier key.
    vsia_bundle_url: str | None = None
    vsia_bundle_sha256: str | None = None
    vsia_hosted_daily_llm_calls: int = 400


@lru_cache
def env() -> Env:
    return Env()


@lru_cache
def settings() -> dict[str, Any]:
    with open(env().vsia_settings_file) as f:
        return yaml.safe_load(f)


def llm_provider() -> str:
    return env().vsia_llm_provider or settings()["llm"]["default_provider"]


def llm_model(provider: str | None = None) -> str:
    provider = provider or llm_provider()
    if env().vsia_llm_model and provider == llm_provider():
        return env().vsia_llm_model
    return settings()["llm"]["providers"][provider]["model"]


def routing_file(provider: str) -> Path:
    return DATA_DIR / "models" / f"routing_{provider}.json"


def confidence_threshold(provider: str | None = None) -> float:
    """Env override, else the threshold tuned on the calibration split for this provider, else the default."""
    if env().vsia_confidence_threshold is not None:
        return env().vsia_confidence_threshold
    if provider and routing_file(provider).exists():
        import json
        return float(json.loads(routing_file(provider).read_text())["threshold"])
    return settings()["routing"]["confidence_threshold"]


def components() -> list[str]:
    return list(settings()["components"])


def severity_levels() -> dict[str, str]:
    return dict(settings()["severity"]["levels"])
