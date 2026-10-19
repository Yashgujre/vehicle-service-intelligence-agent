# ADR-0072: Serve the public dashboard from a redacted parquet snapshot, not a live database

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer (author)
- **Component:** dashboard
- **PRD link:** FR-8, FR-11 (PII), NFR cost

## Context

The public demo runs on Streamlit Community Cloud. It cannot reach the laptop SQLite file. On the VM,
Postgres sits on an internal-only Docker network (ADR-0083), so it is not reachable either. The VM API
exposes triage and review endpoints but no read endpoints for dashboard aggregates, and the VM may be
stopped between demos. Community Cloud apps also sleep after 12 hours without traffic.

## Decision

`scripts/export_demo_snapshot.py` writes small parquet files of the dashboard tables to `app/demo_data/`.
`app/data.py` reads them when `VSIA_DEMO_SNAPSHOT=1`, when the SQLite file does not exist, when the
database is unreachable, or when it holds no complaints. Demo mode is always read-only.

What goes into the snapshot:
- complaints without narrative text;
- redacted narratives only for the triage and review subset;
- the latest triage record per complaint, capped at 3,000 by default, with free text inside JSON redacted;
- the latest forecast run, spike alerts, eval runs and routing curves;
- LLM cost aggregates only, with no per-call rows.

The script fails if the snapshot exceeds 10 MB. The first export, on 2026-10-19, was 152,565 bytes.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Parquet snapshot in the repo (chosen) | Works with zero infrastructure; fast; reviewable; no secrets in the cloud app | Data is as old as the last export; must be re-exported and committed |
| B. Read the VM API over HTTPS | Live data | VM must be up; API needs new aggregate endpoints; a token in Streamlit secrets; slower cold start |
| C. Expose Postgres to Community Cloud | Live data, no new code | Breaks ADR-0083; database credentials on a third-party host |
| D. Hosted free Postgres replica | Live-ish | Another account, sync job and credential to maintain |

## Trade-offs accepted

The public demo is not live, and the export time is shown in the sidebar and on the About page. Review
writes are disabled in the public deploy.

## Consequences

Re-run the export after each triage, forecast or eval batch you want to show. Check the manifest row
counts before committing. The same code path serves live and demo mode, and tests check that both modes
give the same KPIs.

## Revisit when

The demo needs data fresher than the last export, or the API gains read endpoints that make option B a
small change.
