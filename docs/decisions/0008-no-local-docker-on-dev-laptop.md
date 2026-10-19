# ADR-0008: Run the stack natively on the laptop; Docker Compose targets the VM

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer
- **Component:** infrastructure
- **PRD link:** FR-10, Weekend 1 ("Docker Compose running n8n, Postgres, MLflow, and Open WebUI locally")

## Context

The development laptop had about 7 GB of free disk. The Compose stack images (n8n, Postgres, MLflow,
Open WebUI, the API) total several GB before data, Open WebUI alone is large, and Docker Desktop's VM
disk grows on top of that. Docker was not running at build time.

## Decision

On the laptop, run the Python service, the pipelines, the Streamlit app and MLflow natively from the
virtual environment, with SQLite and Ollama. The Docker Compose file and Terraform target the Oracle
Cloud VM. Compose is validated with `docker compose config` (no daemon needed) and the n8n workflows are
validated as JSON against the verified node types.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Native locally, Compose on the VM (chosen) | Fits the disk; fast iteration | n8n and Open WebUI are not exercised locally |
| B. Full Compose locally | Matches the PRD Weekend 1 checklist | Likely to fill the disk and fail midway |
| C. Run n8n via npx locally | Exercises n8n without Docker | Hundreds of MB of node modules; still heavy |

## Trade-offs accepted

n8n workflows and the Open WebUI pipe are written against verified formats but were not executed at
build time. That gap is listed in the README's "verified vs not yet verified" table.

## Revisit when

At least 15 GB of disk is free, or the VM exists: run `docker compose up` and import the workflows.
