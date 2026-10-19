# ADR-0086: Share one Postgres 16 instance with a database and role per service

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer (author)
- **Component:** infra
- **PRD link:** FR-10

## Context

The VSIA API (ADR-0003) and n8n both need Postgres on the VM; MLflow may later (ADR-0081). Each extra
Postgres container costs memory from a 12 GB budget. Passwords must not be written into files in Git.

## Decision

One `postgres:16-alpine` container with a 1 GiB limit hosts three databases (`vsia`, `n8n`, `mlflow`), each
owned by its own login role. `infra/compose/postgres-init.sql` creates them on first start, reading the
passwords from the container environment through psql's `\getenv`, and revokes public access to each
database.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. One instance, per-service databases and roles (chosen) | One container and one backup; isolation by role | Shared failure domain and resources |
| B. One Postgres container per service | Strong isolation | Two or three times the memory and backups |
| C. SQLite for n8n and the API on the VM | No database container | n8n and the API recommend Postgres for concurrent writers; no single backup |

## Trade-offs accepted

A Postgres outage stops n8n and the API together. Passwords set at init are not changed by editing `.env`
later; rotation needs `ALTER ROLE`.

## Consequences

`pg_dumpall` backs up everything in one file (`docs/architecture/deployment.md`). Postgres sits only on the
internal network (ADR-0083).

## Revisit when

One service's load affects the other, or the data needs a managed database with point-in-time recovery.
