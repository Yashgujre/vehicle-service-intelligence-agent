# ADR-0074: Cache narrow read queries for five minutes and aggregate in pandas

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer (author)
- **Component:** dashboard
- **PRD link:** FR-8 (page load under 5 seconds on about 10,000 complaints)

## Context

Streamlit reruns the page script on every widget change. Without caching, every filter click would re-query
the database. The data changes at most a few times per day (daily ingestion, triage batches, weekly
forecasts). The same code must also run on parquet snapshots (ADR-0072).

## Decision

- Every loader in `app/data.py` goes through one `st.cache_data` wrapper with `ttl=300` seconds and
  `max_entries=256`. The cache key is the function name, the data-source key and the arguments.
- Loaders select narrow column sets. The complaints loader, for example, drops the narrative text. Filtering
  and aggregation then happen in pandas, which keeps SQL portable between SQLite and Postgres.
- Complaint text is fetched one record at a time for the detail panel.
- The data-source decision is cached with `st.cache_resource` for the same TTL.
- A sidebar "Refresh data" button and every review write clear the caches.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. 5-minute TTL, narrow loads, pandas aggregation (chosen) | One code path for live and demo; measured cold load 1.6 s, warm 0.25 to 0.56 s | Data can be up to 5 minutes stale; whole narrow tables held in memory |
| B. Aggregate in SQL per panel | Less memory | Two implementations (SQL and parquet); dialect differences |
| C. No TTL, clear only on demand | Fastest | Stale until someone clicks refresh; new triage batches stay invisible |
| D. Materialized summary tables written by the pipelines | Very fast | Cross-workstream schema change; more moving parts |

## Trade-offs accepted

Data can be up to 5 minutes old (the sidebar says so). Memory grows linearly with the complaint count. At
10,303 complaints the narrow frame is small.

## Consequences

The measured load times are in `docs/architecture/dashboard.md`. If triage records grow into the hundreds of
thousands, the triage table loader should move to SQL-side filtering and pagination.

## Revisit when

A cold page load exceeds 5 seconds, or the app's memory on Community Cloud approaches its limit.
