# ADR-0003: One SQLAlchemy Core schema; SQLite on the laptop, Postgres on the VM

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer
- **Component:** cross-cutting (storage)
- **PRD link:** FR-1, FR-5, FR-10

## Context

The PRD stores complaints, triage records, the review queue and labels in Postgres. The development
laptop had about 7 GB of free disk and Docker was not running, so a local Postgres container was not a
good default. The VM deployment still needs Postgres (n8n and MLflow use it too).

## Decision

Define every table once in `src/vsia/db.py` with SQLAlchemy Core and portable types (JSON, Date, Boolean).
`DATABASE_URL` selects the engine: SQLite file by default, Postgres in Docker Compose.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. SQLAlchemy Core, SQLite or Postgres (chosen) | Zero setup locally; same code on the VM; tests use a temp file | No Postgres-only features (JSONB indexes, LISTEN/NOTIFY); concurrency limits on SQLite |
| B. Postgres everywhere | One engine, full feature set | Needs Docker or a local install on a disk-constrained laptop |
| C. DuckDB locally | Fast analytics | n8n's Postgres node cannot read it; another engine to explain |

## Trade-offs accepted

SQLite allows one writer at a time, so local batch triage runs single-process. We avoid Postgres-specific
SQL. Schema migrations are `create_all` only; Alembic is deferred.

## Consequences

The n8n Postgres node and the Streamlit dashboard read the same tables on the VM. Locally, the dashboard
reads SQLite.

## Revisit when

More than one writer is needed locally, or a schema change must preserve existing data (add Alembic).
