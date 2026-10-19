# ADR-0089: Host an interactive demo on Streamlit Community Cloud that runs the agent in-process

- **Status:** Accepted. Refines ADR-0072 for the public deploy; the parquet snapshot stays as the fallback.
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer (author)
- **Component:** dashboard, hosted demo
- **PRD link:** FR-4, FR-8, FR-9, NFR cost

## Context

ADR-0072 made the public dashboard a read-only snapshot. That shows results but does not let a visitor use
the product: nobody can triage a complaint or ask a question. The full stack (API, n8n, Open WebUI,
Postgres) is designed for an OCI VM (ADR-0080 onward), which needs an account, credentials and upkeep.
The owner wants a free link that anyone can use.

Streamlit Community Cloud is free, deploys from a GitHub repository, and gives each app up to about 2.7 GB
of memory and 2 CPU cores (Streamlit documentation, figures as of February 2024). Apps sleep after 12 hours
without traffic and wake when a visitor clicks a button.

## Decision

The public app runs the same Python package in-process:

- "Try the agent" calls `vsia.agent.triage()` on a real complaint or on visitor text;
- "Ask the data" calls `vsia.rag.answer()`;
- the existing six dashboard pages read the same SQLite database, now live, so human review works too.

On first start the app downloads the demo data bundle (ADR-0091), embeds queries in-process (ADR-0090) and
calls a free-tier model (ADR-0088). Visitor actions go to a SQLite file inside the container, shared by
visitors and reset when the app restarts.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. In-process agent on Community Cloud (chosen) | Free; one link; full workflow visible; same code as local | Shared, ephemeral state; cold start after sleep; memory ceiling |
| B. Read-only snapshot (ADR-0072) | Simplest; no keys | Visitors cannot try the product |
| C. Hugging Face Spaces (Docker) | 16 GB RAM free tier | Second platform to learn; Docker build and large files need Git LFS; no gain for this workload |
| D. OCI VM with the full stack | Production-like, n8n and Open WebUI included | Account, credentials and upkeep; not needed to judge the agent |

## Trade-offs accepted

- Review decisions and triage runs made by visitors are shared and lost on restart. That suits a demo; the
  sidebar says so.
- Memory budget: embedding model (about 0.5 GB on disk), BM25 over 10,303 complaints and the classifier fit
  well under the ceiling in local tests, but are not measured on Community Cloud yet.
- n8n, Open WebUI, MLflow UI and the API are not part of the hosted demo; they remain documented for the VM
  and run locally.

## Consequences

- New pages `app/views/try_agent.py` and `app/views/ask.py`; navigation groups them under "Try it".
- `app/requirements.txt` adds scikit-learn, joblib, rank-bm25, fastembed, httpx and tenacity, pinned to
  the versions that trained the classifier.
- Deploy steps: `docs/operations/runbooks/hosted-demo.md`.

## Revisit when

The app hits the memory ceiling, visitors need persistent accounts or history, or the VM deploy is funded.
