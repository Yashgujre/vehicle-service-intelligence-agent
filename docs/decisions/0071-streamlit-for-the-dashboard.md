# ADR-0071: Build the dashboard in Streamlit with Plotly, as a native multipage app

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer (author)
- **Component:** dashboard
- **PRD link:** FR-8

## Context

FR-8 asks for one place to see complaint volume, the triage queue, the human review queue, forecasts and
spike alerts, evaluation results and LLM cost. The project is Python end to end, has one author, and the
public demo must cost nothing to host. The dashboard needs a few write actions (review decisions), not a
full web application.

## Decision

Use Streamlit 1.66 with Plotly charts. Pages are declared with `st.navigation` in `app/streamlit_app.py`
and live in `app/views/`. The folder is deliberately not called `pages/`: Streamlit would then also run
its legacy auto-discovered multipage mode, which skipped the entrypoint when a page URL was opened
directly (observed during verification).

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Streamlit + Plotly (chosen) | Pure Python, reuses `vsia` modules directly; forms for review; free Community Cloud hosting; built-in caching | Whole-script reruns; limited layout control; one websocket session per viewer |
| B. Grafana or Metabase on Postgres | Strong time-series panels; SQL-only | Cannot reuse Python logic (redaction, review writes); another service on a 12 GB VM; no free public hosting of our data |
| C. FastAPI + React front end | Full control, fastest UI | Weeks of front-end work for one author; separate build and hosting |
| D. Gradio | Quick ML demos | Weaker for multi-page analytics and tables |

## Trade-offs accepted

Every widget change reruns the page script, so every query goes through `st.cache_data` (ADR-0074).
Styling stays within Streamlit's theme (`.streamlit/config.toml`) plus a Plotly colour sequence.

## Consequences

The dashboard imports `vsia.review`, `vsia.guardrails` and `vsia.observability` instead of duplicating them.
Page scripts are testable headless with `streamlit.testing.v1.AppTest` (see `tests/test_app_data.py`).

## Revisit when

Page loads exceed 5 seconds at the target data size after caching, or more than a handful of concurrent
users need the app.
