# VSIA API service image (FastAPI + triage agent + forecast pipeline). Multi-arch: python:3.11-slim has
# amd64 and arm64 variants, and every dependency ships manylinux wheels for both, so the same file builds
# on the OCI A1 (arm64) VM. Ollama is not included; the container uses hosted LLM APIs (ADR-0080).
#
#   docker build -t vsia-api:local .          (Compose builds it: infra/compose/docker-compose.yml)

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN useradd --create-home --uid 10001 vsia

# Editable install keeps vsia.config.REPO_ROOT at /app, so config/ and data/ resolve as in the repo.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install -e ".[postgres,cloud,mlops]"

COPY config ./config
COPY pipelines ./pipelines
COPY data/raw ./data/raw

# pipelines/ is imported by POST /forecast/run as a top-level package.
ENV PYTHONPATH=/app \
    VSIA_SETTINGS_FILE=/app/config/settings.yaml

RUN mkdir -p /app/data/models /app/data/index /app/data/docs /mlflow/artifacts \
    && chown -R vsia:vsia /app/data /mlflow

USER vsia
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)"

CMD ["uvicorn", "vsia.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
