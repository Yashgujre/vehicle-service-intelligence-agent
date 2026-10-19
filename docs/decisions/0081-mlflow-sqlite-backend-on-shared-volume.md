# ADR-0081: Use a SQLite MLflow backend on a volume shared with the API container

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer (author)
- **Component:** infra
- **PRD link:** FR-7, FR-8

## Context

The forecast pipeline (`pipelines/forecast.py`) logs runs and registers a champion model with an alias,
so MLflow needs a database-backed store (the Model Registry does not work on the legacy file store).
MLflow 3.17.1 defaults to SQLite (research section 7). Using the stack's Postgres needs `psycopg2` in the
MLflow image, and whether the slim `ghcr.io/mlflow/mlflow` image includes it is unverified. The pipeline
also creates its experiment with a `file://` artifact location under `MLFLOW_ARTIFACT_ROOT`, which means
the client writes artifacts directly to that path rather than uploading through the server.

## Decision

Run `mlflow server --backend-store-uri sqlite:////mlflow/mlflow.db --artifacts-destination
/mlflow/artifacts` on the `mlflow-data` volume, and mount the same volume at `/mlflow` in the API
container with `MLFLOW_TRACKING_URI=http://mlflow:5000` and `MLFLOW_ARTIFACT_ROOT=/mlflow/artifacts`. The
`mlflow` Postgres database and role are still created by the init script so a later switch is one line.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. SQLite on a shared volume (chosen) | Verified default; supports the registry; no extra driver; artifacts readable by both containers at the same path | Single writer; SQLite file must be backed up separately from Postgres |
| B. Postgres backend | One database to back up; concurrent writers | Needs psycopg2 (unverified in the slim image, or the larger `-full` image) |
| C. Legacy file store (`./mlruns`) | No database | No Model Registry; labelled legacy |
| D. Proxied artifact uploads (`mlflow-artifacts:/`) | API needs no shared volume | Requires changing the pipeline's experiment creation (owned by the forecasting workstream) |

## Trade-offs accepted

The API and MLflow containers are coupled through a volume. Write concurrency is low (one weekly run), so
SQLite's single-writer limit does not matter.

## Consequences

Back up the `mlflow-data` volume (tar) alongside the Postgres dump. MLflow is reachable only through an
SSH tunnel (`127.0.0.1:5000`).

## Revisit when

The slim image is confirmed to include psycopg2 (switch to Postgres), several pipelines write runs
concurrently, or the forecasting workstream moves to proxied artifact storage.
