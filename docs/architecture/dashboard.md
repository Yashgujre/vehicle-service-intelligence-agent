# Dashboard (FR-8)

The Streamlit dashboard is the operations, review and evaluation view over the project database. Code is in
`app/`: `streamlit_app.py` is the entrypoint, `views/` holds one script per page, `data.py` is the read layer
and `ui.py` holds shared helpers. Decisions: ADR-0071 (Streamlit), ADR-0072 (demo snapshot), ADR-0073
(review UI), ADR-0074 (caching).

## Pages and data sources

| Page (URL) | Panel | Source |
|---|---|---|
| Overview (`/`) | KPIs: complaints, last ingestion run and rows inserted, triaged, auto-routed %, pending reviews, active spike alerts, LLM calls, LLM cost to date, cost per 1,000 triaged | `complaints`, `ingestion_runs`, `triage_records`, `review_queue`, `spike_alerts` + `forecasts`, `vsia.observability.cost_latency_summary()` |
| | Weekly complaint volume (weeks start Monday, as in the forecast pipeline; the trailing partial week is dropped) and top components | `complaints` (NHTSA-coded `component_primary`, shown as reference data, never model input) |
| | Filters: make, model year, date filed | in-memory filter on the cached complaints frame |
| Triage queue (`/triage`) | Latest triage record per complaint (toggle shows all runs) joined to vehicle fields; filters; detail panel with redacted complaint text, structured output, confidence signals, review reasons and cited recalls linked to `https://www.nhtsa.gov/recalls?nhtsaId=<campaign>` | `triage_records`, `complaints`, `recalls` |
| Human review (`/review`) | Review stats, pending items (lowest confidence first), one accept-or-correct form per item | `vsia.review.pending()` plus `triage_records.confidence_signals.candidates`; writes via `vsia.review.decide()` |
| Trends and spikes (`/trends`) | Weekly complaints by selected components; forecast vs actual with interval band for holdout and future weeks (latest `run_id`); spike alerts with ratio and an active flag | `complaints`, `forecasts`, `spike_alerts` |
| Evaluation and cost (`/evaluation`) | Latest eval run per provider, model and split, plus a provider comparison chart when several providers exist; routing threshold curve (coverage vs auto-routed accuracy); LLM calls, error rate, p50/p95 latency and cost per 1,000 calls by provider, model and purpose | `eval_runs` (the nested `metrics` dict written by `eval/run_eval.py`), `data/models/routing_<provider>.json`, `cost_latency_summary()` |
| About (`/about`) | Architecture paragraph, pipeline pattern and how it transfers to other domains, NHTSA attribution, link placeholders | static |

Definitions:
- **Triaged:** distinct complaints with at least one triage record. **Auto-routed %** uses the latest record
  per complaint.
- **Cost per 1,000 triaged:** the sum of `triage_records.cost_usd` divided by the number of triage runs, times 1,000.
- **Active spike alert:** an alert in the last 4 weeks of the latest forecast holdout window. This is the same
  window the forecast pipeline calls "current".

Every table can be empty while other workstreams fill it. Each panel then shows
"No data yet for <panel>: run `<command>`", with the command that fills the table:
- `vsia ingest`;
- `vsia triage --limit 50`;
- `python -m pipelines.forecast all`;
- `python -m eval.run_eval all --provider ollama`;
- `python -m eval.run_eval calibrate --provider <provider>`.

## PII

Complaint narratives and every string inside the triage `output` and `confidence_signals` JSON pass through
`vsia.guardrails.redact()` before display. The heuristic provider copies the first 160 characters of the raw
complaint into `output.extracted.symptom`, so redacting the JSON is required, not optional. The demo snapshot
stores already-redacted text.

## Data source modes

`app/data.py:resolve_source()` picks the mode once and caches the result for 5 minutes:

1. **demo**, when `VSIA_DEMO_SNAPSHOT=1`, or when the SQLite file is missing, the database is unreachable or
   it holds no complaints. The app then reads the parquet files in `app/demo_data/`.
2. **live**, otherwise. The app reads `vsia.db.engine()` (SQLite at `data/vsia.db`, or Postgres through
   `DATABASE_URL`). Queries use SQLAlchemy Core and are portable.
3. **empty**, when neither is available. Every page shows its "no data yet" state.

Writes happen only in live mode with `VSIA_READONLY` unset. Demo mode is always read-only. The sidebar
shows the active mode and the snapshot export time.

### Demo snapshot

```bash
python scripts/export_demo_snapshot.py            # writes app/demo_data/*.parquet and manifest.json
python scripts/export_demo_snapshot.py --max-triage 1000 --max-mb 5
```

The script needs a live database and fails above the size limit (10 MB by default). The first export, on
2026-10-19 06:12 UTC, wrote 152,565 bytes. Its row counts were 10,303 complaints, 407 recall rows,
3 ingestion runs and 2 LLM summary rows, with 0 triage, forecast and eval rows because those tables were
still empty. Re-export and commit after new triage, forecast or eval runs.

## Caching and performance

Every loader goes through `st.cache_data` with a 300-second TTL (ADR-0074). The sidebar "Refresh data" button
and every review write clear the cache.

Measured on 2026-10-18 on the dev laptop, a MacBook running Streamlit 1.66.0 headless with 10,303
complaints in SQLite. The method opened each page in a same-origin iframe in the Cursor browser and timed
from the request until the page title and all KPI metrics and Plotly charts had rendered, with the
Streamlit "running" indicator gone:

| Page | Mode | Cold (first request after server start) | Warm (cached) |
|---|---|---|---|
| Overview | live SQLite | 1.64 s | 0.33 to 0.53 s (3 loads) |
| Overview | demo snapshot | 1.60 s | 0.25 to 0.56 s (2 loads) |
| Triage, Review, Trends, Evaluation, About | live SQLite | not separately measured cold | 0.17 to 0.41 s (title rendered; tables mostly empty) |

The HTML shell (`curl http://localhost:8599/`) returned in about 2 ms, and `/_stcore/health` returned `ok`.
The triage and forecast tables were empty at measurement time, so the Triage, Review and Trends forecast
panels are not yet measured with data.

Screenshots of the live database state at measurement time are in `docs/assets/`:
- `dashboard-overview.png`
- `dashboard-triage.png`
- `dashboard-review.png`
- `dashboard-trends.png`
- `dashboard-evaluation.png`
- `dashboard-about.png`

The Triage and Review screenshots show the empty states. Retake them after triage runs.

## Run locally

```bash
source .venv/bin/activate
streamlit run app/streamlit_app.py                  # live database, review writes enabled
VSIA_READONLY=1 streamlit run app/streamlit_app.py  # live database, read-only
VSIA_DEMO_SNAPSHOT=1 streamlit run app/streamlit_app.py
pytest tests/test_app_data.py
```

## Deploy to Streamlit Community Cloud

1. Export and commit the snapshot (`python scripts/export_demo_snapshot.py`), after checking
   `app/demo_data/manifest.json`.
2. In Community Cloud, create an app from the repository, set the entrypoint to `app/streamlit_app.py`, and
   pick Python 3.11 in Advanced settings.
3. Dependencies: Community Cloud looks in the entrypoint directory first, then the repository root, and uses
   the first dependency file it finds (`uv.lock`, `Pipfile`, `environment.yml`, `requirements.txt`, then
   `pyproject.toml`). `app/requirements.txt` therefore wins over the root `pyproject.toml`, which would
   otherwise be read as a Poetry file. It is a copy of `requirements-streamlit.txt` (pinned:
   `streamlit==1.66.0`, `plotly`, `pandas`, `pyarrow`, `sqlalchemy`, `pydantic`, `pydantic-settings`,
   `pyyaml`, `numpy`). A test keeps the two files identical.
4. Secrets: paste TOML into Advanced settings. Never commit `.streamlit/secrets.toml`. For the public demo:

   ```toml
   VSIA_DEMO_SNAPSHOT = "1"
   VSIA_READONLY = "1"
   ```

   Root-level secrets are also exposed as environment variables, which is how `app/data.py` reads them. No
   API keys are needed because the dashboard makes no LLM calls.
5. Theme: only the repository-root `.streamlit/config.toml` is read, including on Community Cloud.
6. Sleep: an app with no traffic for 12 hours goes to sleep, and the next visitor must click "Yes, get this
   app back up!" and wait for a cold start. Open the app shortly before a demo.

## Known limits

- Streamlit has no authentication. Run the writable mode only locally or on a private network.
- Demo data is as old as the last export.
- `docs/architecture/deployment.md` describes the dashboard as reading the VM API. The current design reads
  the database or the snapshot (ADR-0072). That row should be updated by the infrastructure workstream.
