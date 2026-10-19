# Dashboard (FR-8)

The Streamlit dashboard is the operations, review and evaluation view over the project database. Code is in
`app/`: `streamlit_app.py` is the entrypoint, `views/` holds one script per page, `data.py` is the read layer
and `ui.py` holds shared helpers. Decisions: ADR-0071 (Streamlit), ADR-0072 (demo snapshot), ADR-0073
(review UI), ADR-0074 (caching), ADR-0088 to ADR-0092 (hosted interactive demo). `hosted.py` holds the
hosted demo support: data bundle bootstrap, AI model picker and quota guard.

## Pages and data sources

Navigation has two groups: "Try it" (Try the agent, Ask the data) and "Operate" (the six original pages).
"Try the agent" is the default page.

| Page (URL) | Panel | Source |
|---|---|---|
| Try the agent (`/try`, default) | Pick a real complaint (make, model, "crash or fire only" filter, random pick) or write one (three examples: brake failure, personal details, prompt injection); runs `vsia.agent.triage()` and shows route, component, severity, calibrated confidence against the threshold, review reasons, NHTSA's own coding for comparison (hidden from the model), linked recalls, extracted fields and a seven-step trace (redaction, injection check, recall tools, model call, grounding, severity rule, confidence and route) | `complaints`, `recalls`; writes `triage_records` and `review_queue` for picked complaints only (run id `playground-<session>`); written complaints are not persisted |
| Ask the data (`/ask`) | RAG chat with four example questions (one out of scope); answers link cited recalls; caption shows intent, filters, verified citations and latency. With the offline option it lists the most relevant retrieved sources without an AI-written answer | `vsia.rag.answer()`; `vsia.retrieval.search_sources()` offline; conversation kept in session state only |
| Overview (`/overview`) | KPIs: complaints, last ingestion run and rows inserted, triaged, auto-routed %, pending reviews, active spike alerts, LLM calls, LLM cost to date, cost per 1,000 triaged | `complaints`, `ingestion_runs`, `triage_records`, `review_queue`, `spike_alerts` + `forecasts`, `vsia.observability.cost_latency_summary()` |
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
shows the active mode and the snapshot export time. "Try the agent" and "Ask the data" need live mode; in
demo mode they show a warning and stop.

## Hosted demo: bootstrap, AI model picker and quota guard

These run only when the app is deployed as the hosted demo (ADR-0089); local runs are unchanged.

**Bootstrap** (`hosted.bootstrap()`, called by `streamlit_app.py` before the data source is resolved).
When `VSIA_BUNDLE_URL` is set, it sets `VSIA_EMBED_PROVIDER=fastembed` (ADR-0090) and, if `data/vsia.db`
and the bundle marker are missing, downloads the demo data bundle, checks it against `VSIA_BUNDLE_SHA256`
and unpacks only regular files and directories under `data/` (`vsia.bundle.ensure`, ADR-0091). The data
source then resolves to live mode against the bundled SQLite database. Without `VSIA_BUNDLE_URL` the app
falls back to the snapshot rules above.

**AI model picker** (`hosted.model_picker()`, in the sidebar of both "Try it" pages). Options, in order:

| Option | When offered | Source label |
|---|---|---|
| Google Gemini, free (shared key) | `GEMINI_API_KEY` is set | hosted |
| Groq, free (shared key) | `GROQ_API_KEY` is set | hosted |
| Anthropic Claude or OpenAI (host key) | The host set that key | hosted |
| Ollama, local model | An Ollama server answers (development) | local |
| Use my own API key | Always | own: provider choice (Gemini, Groq, OpenAI, Anthropic) and a password field; with no key entered, requests fall back to the offline classifier |
| Offline classifier (no AI call) | Always | offline: provider `heuristic`, the TF-IDF baseline |

A visitor's key lives only in that browser session's state and is passed per request through
`vsia.llm.use_keys()`; it is never written to the database, logs or `llm_calls` (ADR-0092). On the triage
page, when the shared Gemini key answers 429 and `GROQ_API_KEY` exists, the run is retried once on Groq
and the page says so. Any other AI failure shows the agent's designed failure mode: offline classifier
output, routed to human review, with the reason.

**Quota guard** (`hosted.quota_block()`, ADR-0092). Applies only to the shared key:

- at most 15 AI calls per browser session (`SESSION_AI_RUNS`); a triage run counts one call and a chat
  question two (plan and answer);
- at most `VSIA_HOSTED_DAILY_LLM_CALLS` calls (default 400) per provider per day, counted from `llm_calls`
  since midnight Pacific, when Gemini quotas reset.

When a cap is hit the page explains why and offers the visitor's own key or the offline classifier. The
sidebar shows how many shared calls the session has left.

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

The shareable deployment is the interactive hosted demo: follow
[the hosted demo runbook](../operations/runbooks/hosted-demo.md) (Gemini key, data bundle release asset,
secrets `GEMINI_API_KEY`, optional `GROQ_API_KEY`, `VSIA_BUNDLE_URL`, `VSIA_BUNDLE_SHA256`, optional
`VSIA_HOSTED_DAILY_LLM_CALLS`). The steps below deploy the read-only snapshot, which remains the fallback
(ADR-0072, refined by ADR-0089); steps 3, 5 and 6 apply to both.

1. Export and commit the snapshot (`python scripts/export_demo_snapshot.py`), after checking
   `app/demo_data/manifest.json`.
2. In Community Cloud, create an app from the repository, set the entrypoint to `app/streamlit_app.py`, and
   pick Python 3.11 in Advanced settings.
3. Dependencies: Community Cloud looks in the entrypoint directory first, then the repository root, and uses
   the first dependency file it finds (`uv.lock`, `Pipfile`, `environment.yml`, `requirements.txt`, then
   `pyproject.toml`). `app/requirements.txt` therefore wins over the root `pyproject.toml`, which would
   otherwise be read as a Poetry file. It is a copy of `requirements-streamlit.txt` (pinned:
   `streamlit==1.66.0`, `plotly`, `pandas`, `pyarrow`, `sqlalchemy`, `pydantic`, `pydantic-settings`,
   `pyyaml`, `numpy`, plus `httpx`, `tenacity`, `scikit-learn`, `joblib`, `rank-bm25` and `fastembed` for
   the in-process agent, ADR-0089). A test keeps the two files identical.
4. Secrets: paste TOML into Advanced settings. Never commit `.streamlit/secrets.toml`. For a snapshot-only
   deployment:

   ```toml
   VSIA_DEMO_SNAPSHOT = "1"
   VSIA_READONLY = "1"
   ```

   Root-level secrets are also exposed as environment variables, which is how `app/data.py` reads them. A
   snapshot-only deployment needs no API keys; the "Try it" pages then show a warning instead of running.
5. Theme: only the repository-root `.streamlit/config.toml` is read, including on Community Cloud. It defines
   `[theme.light]` and `[theme.dark]`, so each visitor starts in the theme that matches their system setting
   and can switch between System, Light and Dark in the top-right menu. Streamlit has no per-visitor theme
   API, so there is no in-page toggle; a server-side switch would change the theme for every visitor. Charts
   use `theme="streamlit"` and set no background or font colours (`app/ui.py`), so they follow the active
   theme; the series palette uses mid-luminance colours that read on both backgrounds.
6. Sleep: an app with no traffic for 12 hours goes to sleep, and the next visitor must click "Yes, get this
   app back up!" and wait for a cold start. Open the app shortly before a demo.

## Known limits

- Streamlit has no authentication. Run the writable mode only locally or on a private network. The hosted
  demo is the deliberate exception: its database is public demo data, shared by visitors and reset on
  restart, so open review writes are accepted (ADR-0089).
- Demo data is as old as the last export or the last bundle.
- Hosted demo memory use, cold-start time and latency on Community Cloud are not yet measured; the page
  timings above are from the laptop and predate the "Try it" pages.
- `docs/architecture/deployment.md` describes the dashboard as reading the database or the snapshot, which
  matches the code, and no longer lists `VSIA_API_TOKEN` as a Streamlit secret.
