# Data dictionary

Every table and column defined in `src/vsia/db.py`, with its SQLAlchemy type, meaning, PII flag, the code
that writes it (producer) and the main readers (consumers). The schema is the contract for every stage
(AGENTS.md, "Contracts you can rely on"); a change to it needs a decision record (ADR-0003 covers the
portable SQLAlchemy Core design). The structure follows the schema section of the Open Data Contract
Standard (field, type, description, PII flag), as recommended in
`docs/research/01_documentation_process_research.md` section 5.

Related documents: [data lineage](lineage.md), [end-to-end data flow](../architecture/data-flow.md),
[NHTSA corpus datasheet](datasheet-nhtsa-corpus.md), [gold set datasheet](datasheet-gold-set.md),
[design doc](../design/design-doc.md).

## Conventions

- **Types** are SQLAlchemy Core types. The same schema runs on SQLite (laptop, `data/vsia.db`) and
  Postgres 16 (VM) (ADR-0003). `JSON` is stored as text on SQLite and as `json` on Postgres.
- **Timestamps** default to `datetime.utcnow` in Python, so they are naive UTC values.
- **Schema migrations** are `metadata.create_all()` only. There is no Alembic; adding a column to an
  existing database needs a manual `ALTER TABLE` (ADR-0003, "Trade-offs accepted").
- **PII flag** values:
  - `yes`: the column can hold personal data as stored.
  - `quasi`: not identifying alone, but can help re-identify a person when combined with other data.
  - `possible`: normally free of personal data, but a known code path can copy free text into it (the
    path is named in the description).
  - `no`: no personal data.
- **Label leakage** (ADR-0005, AGENTS.md rule 3): `complaints.components_raw` and
  `complaints.component_primary` are NHTSA's coded labels. They are evaluation ground truth and training
  labels for the baseline classifier. They are never sent to an LLM, never embedded and never stored in
  complaint retrieval metadata (ADR-0033).

## Row counts at the time of writing

Counted with read-only `sqlite3` SELECTs on `data/vsia.db` on 2026-10-19. Tables written by the triage,
forecast and evaluation stages were empty in this database at that time; their counts will change as those
jobs run.

| Table | Rows | Note |
|---|---|---|
| `complaints` | 10,303 | 8 makes, 24 distinct model strings, filed 2022-01-02 to 2026-10-15 |
| `recalls` | 407 | 200 distinct campaign numbers |
| `recall_documents` | 150 | 80 Part 573 reports, 70 owner letters, 80 campaigns |
| `ingestion_runs` | 3 | two complaint runs, one recall run |
| `labels` | 500 | all `source = gold_silver` (200 gold + 300 calibration) |
| `llm_calls` | 3 | two `smoke` calls, one `triage` call |
| `triage_records` | 0 | |
| `review_queue` | 0 | |
| `forecasts` | 0 | |
| `spike_alerts` | 0 | |
| `eval_runs` | 0 | |

## Table ownership

From the `src/vsia/db.py` module docstring:

| Tables | Owner workstream | Producing code |
|---|---|---|
| `complaints`, `recalls`, `ingestion_runs` | ingestion | `vsia.ingest` |
| `recall_documents` | document parsing | `vsia.documents` |
| `triage_records`, `review_queue`, `labels` | triage agent and human review | `vsia.agent`, `vsia.review` (and `eval/build_gold.py` for `labels`) |
| `llm_calls` | LLM gateway | `vsia.llm` through `vsia.db.log_llm_call` |
| `forecasts`, `spike_alerts` | forecasting | `pipelines/forecast.py` |
| `eval_runs` | evaluation | `eval/run_eval.py` |

---

## complaints

One row per NHTSA owner complaint (ODI number) in the configured segment (ADR-0004). Loaded idempotently:
an existing `odi_number` is skipped, never overwritten.

- **Producer:** `vsia.ingest.ingest_complaints()` (CLI `vsia ingest`, API `POST /ingest/daily`, n8n
  workflow 01).
- **Consumers:** `vsia.agent.load_complaint`, `vsia.api.triage_pending`, `vsia.review.pending`,
  `vsia.rag._stats`, `scripts/build_index.py` (complaints namespace), `scripts/fetch_recall_docs.py`
  (campaign ranking), `pipelines/forecast.py` (weekly panel), `eval/build_gold.py`, `vsia.classifier`,
  `eval/run_eval.py` (field accuracy and S1 truth), `app/data.py`.

| Column | Type | Key / index | Description | PII | Source field or rule |
|---|---|---|---|---|---|
| `odi_number` | Integer | primary key | NHTSA Office of Defects Investigation complaint number | no | `odiNumber` |
| `make` | String(64) | not null, index | Make, upper case (FORD, TESLA, RIVIAN, HYUNDAI, KIA, CHEVROLET, TOYOTA, VOLKSWAGEN) | no | query make, upper-cased |
| `model` | String(128) | not null, index | NHTSA canonical model name from the complaint's own product record, upper case (ADR-0004 point 3) | no | `products[].productModel` for the matching make, else the query string |
| `model_year` | Integer | not null, index | Model year, 2021 to 2026 | no | query model year |
| `manufacturer` | String(128) | | Manufacturer legal name as reported by NHTSA | no | `manufacturer` |
| `date_filed` | Date | index | Date the complaint was filed with NHTSA; drives the forecast weeks | no | `dateComplaintFiled` |
| `date_incident` | Date | | Date of the incident as reported by the owner | quasi | `dateOfIncident` |
| `crash` | Boolean | default false | Owner reported a crash | no | `crash` |
| `fire` | Boolean | default false | Owner reported a fire | no | `fire` |
| `injuries` | Integer | default 0 | Number of injuries reported | no | `numberOfInjuries` |
| `deaths` | Integer | default 0 | Number of deaths reported | no | `numberOfDeaths` |
| `vin_prefix` | String(17) | | VIN as published by NHTSA. In the loaded data 10,242 rows hold 11 characters, 1 row holds 9 and 60 are null; NHTSA does not publish the full 17-character VIN | quasi | `vin` |
| `components_raw` | Text | | NHTSA-coded component string, comma-joined, possibly several labels. **Ground truth; never model input** (ADR-0005) | no | `components` |
| `component_primary` | String(64) | index | First specific canonical component from `components_raw`; `OTHER` only when nothing specific is listed (`vsia.taxonomy.primary_component`). **Ground truth; never model input.** Also the series key of the forecast | no | derived at load |
| `summary` | Text | not null | Owner's free-text narrative, stored **unredacted** as received. Redaction happens at each use: before the LLM (`vsia.agent`), before embedding (`scripts/build_index.py`, `vsia.retrieval`), before the classifier (`vsia.classifier`), before display (`app/data.py`) and in the gold files (`eval/build_gold.py`) | yes | `summary`, stripped |
| `ingested_at` | DateTime | default utcnow | Insert time; the only link from a row back to its ingestion run (see [lineage](lineage.md)) | no | set at insert |
| `source` | String(32) | default `api` | Load path; `api` for every current row. The flat-file backfill path (`complaints_backfill`) is documented in ADR-0004 but not run | no | `ingest_complaints(source=...)` |

## recalls

One row per recall campaign and vehicle (campaign number x make x model x model year), as returned by the
NHTSA recalls-by-vehicle API.

- **Producer:** `vsia.ingest.ingest_recalls()` (same triggers as complaints). Duplicate
  `(campaign_number, make, model, model_year)` keys are skipped.
- **Consumers:** `vsia.tools.recall_lookup` (agent tool), `scripts/build_index.py` (recalls and
  recall_docs namespaces), `vsia.documents._make_for`, `scripts/fetch_recall_docs.py`,
  `pipelines/forecast.py` (`recall_dates`, weak external check on alerts), `eval/build_gold.py` (silver
  recall labels), `app/data.py`.

| Column | Type | Key / index | Description | PII | Source field or rule |
|---|---|---|---|---|---|
| `id` | Integer | primary key, autoincrement | Surrogate key | no | generated |
| `campaign_number` | String(16) | not null, index | NHTSA campaign number, for example `24V935000` | no | `NHTSACampaignNumber` |
| `make` | String(64) | not null | Make, upper case | no | `Make` |
| `model` | String(128) | not null | Model string as the recall API returns it (differs from complaint strings; see ADR-0004 and `vsia.retrieval.model_family`) | no | `Model` |
| `model_year` | Integer | not null | Model year | no | `ModelYear` |
| `manufacturer` | String(128) | | Manufacturer | no | `Manufacturer` |
| `report_date` | Date | | Date NHTSA received the Part 573 report (API dates are DD/MM/YYYY) | no | `ReportReceivedDate` |
| `component_raw` | Text | | NHTSA recall component string | no | `Component` |
| `component_primary` | String(64) | index | Canonical primary component (`vsia.taxonomy.primary_component`). Used for the component-overlap rule (ADR-0063) and indexed in recall records; this is a recall attribute, not complaint ground truth | no | derived at load |
| `summary` | Text | | Defect summary | no | `Summary` |
| `consequence` | Text | | Safety consequence | no | `Consequence` |
| `remedy` | Text | | Remedy description | no | `Remedy` |
| `park_it` | Boolean | default false | Park-it advisory | no | `parkIt` |
| `park_outside` | Boolean | default false | Park-outside advisory | no | `parkOutSide` |
| `ota` | Boolean | default false | Remedy is an over-the-air update | no | `overTheAirUpdate` |

Unique constraint `uq_recall_vehicle` on (`campaign_number`, `make`, `model`, `model_year`). The table has
no insert timestamp, so a recall row cannot be tied to the ingestion run that loaded it (see
[lineage](lineage.md), "Known lineage gaps").

## recall_documents

One row per parsed recall PDF (Part 573 Safety Recall Report `RCLRPT` or owner notification letter
`RCONL`).

- **Producer:** `vsia.documents.process()` (`python -m vsia.documents`), from the PDFs and manifest written
  by `scripts/fetch_recall_docs.py`. Re-processing a document deletes and re-inserts the row with the same
  `source_url`.
- **Consumers:** `scripts/build_index.py` (recall_docs namespace chunks and Part 573 vehicle lists),
  `vsia.documents.process` itself (skip and coverage checks).

| Column | Type | Key / index | Description | PII | Notes |
|---|---|---|---|---|---|
| `id` | Integer | primary key, autoincrement | Surrogate key | no | |
| `campaign_number` | String(16) | not null, index | Campaign the document belongs to; taken from the manifest, never from a model (ADR-0032 point 4) | no | |
| `doc_type` | String(32) | | `RCLRPT` (Part 573 report) or `RCONL` (owner letter) | no | |
| `source_url` | Text | | `static.nhtsa.gov` URL of the PDF; the natural key used for idempotency and the link to `data/docs/manifest.json` (which holds the SHA-256) | no | |
| `parser` | String(32) | | `pypdf`, `pypdf+tesseract` (OCR fallback) or `llamaparse` (ADR-0031) | no | 140 `pypdf`, 10 `pypdf+tesseract` |
| `pages` | Integer | | Page count | no | 481 pages in total |
| `markdown` | Text | | Parsed text as markdown with `<!-- page N -->` markers, **redacted with `guardrails.redact` before storage** (owner letters carry sample names and addresses; Part 573 reports carry company phone numbers) | possible | residual PII only where the regex redactor misses it |
| `extraction` | JSON | | `RecallDocExtraction` fields (campaign_number, component, defect_summary, remedy, affected_models, model_years, source_url) plus `method`: `rules`, `llm`, `covered_by_part573` or `llm_failed` | no | 88 `rules`, 62 `covered_by_part573`, 0 `llm` |
| `extraction_valid` | Boolean | | True when the extraction passed `RecallDocExtraction` validation | no | 88 true |
| `parsed_at` | DateTime | default utcnow | Parse time | no | |

## triage_records

One row per triage run of one complaint: the validated model output plus provenance, confidence signals
and route. The same complaint can have several rows (different providers, evaluation runs, re-runs).

- **Producers:** `vsia.agent.save()`, called by `vsia.agent.triage(persist=True)` from `POST /triage`,
  `POST /triage/pending` (n8n workflow 01), `vsia triage` (CLI) and `eval/run_eval.py predict` (with
  `run_id` prefixed `eval-`, ADR-0064). The n8n-native variant (workflow 05) also inserts rows directly
  through its Postgres node, with `run_id = n8n-native-<execution id>` (ADR-0075).
- **Consumers:** `vsia.review.pending` and `vsia.review.decide` (join), `vsia.api.triage_pending` (to skip
  already-triaged complaints), `app/data.py` (triage queue, KPIs), `scripts/export_demo_snapshot.py`.

| Column | Type | Key / index | Description | PII | Notes |
|---|---|---|---|---|---|
| `id` | Integer | primary key, autoincrement | Surrogate key; referenced by `review_queue.triage_record_id` | no | |
| `odi_number` | Integer | not null, index | Complaint triaged | no | logical foreign key to `complaints` |
| `run_id` | String(64) | index | Batch or request id from `vsia.agent.new_run_id(prefix)`: `<prefix>-YYYYMMDD-HHMMSS-<6 hex>`. Prefixes in code: `api`, `batch`, `cli`, `eval-<split>-<provider>`; workflow 05 uses `n8n-native-<execution>` | no | |
| `schema_version` | String(8) | | `TRIAGE_SCHEMA_VERSION` from `vsia.schemas` (currently `1.0`) | no | |
| `component` | String(64) | index | Final primary component after taxonomy normalisation | no | copy of `output.component` |
| `severity` | String(4) | | Final severity `S1` to `S4`, after the crash/fire/injury/death rule (ADR-0062) | no | copy of `output.severity` |
| `recall_campaigns` | JSON | | List of campaign numbers kept after grounding and component overlap (ADR-0063) | no | |
| `confidence` | Float | | Routing confidence in [0, 1], from the calibrator or the fallback blend (ADR-0061) | no | |
| `confidence_signals` | JSON | | Every signal and decision trace: `pii_redactions`, `injection_score`, `n_candidates`, `candidates`, `retrieval_top_score`, `retrieval_ranked`, `schema_retry`, `llm_error` (first 300 characters), `component_off_taxonomy`, `citations_dropped`, `llm_severity`, `severity_rule_override`, `llm_confidence`, `clf_prob_of_llm_label`, `clf_max_prob`, `clf_top_label`, `agree`, `confidence_method`, `review_reasons` | possible | `llm_error` holds an exception message that can include fragments of model output |
| `route` | String(8) | index | `auto` or `review` | no | |
| `output` | JSON | | Full validated `TriageOutput`: extracted fields, component, secondary components, severity and reason, recall matches with rationale, model confidence, injection flag | possible | with provider `heuristic` (or after an LLM failure), `output.extracted.symptom` is the first 160 characters of the **unredacted** complaint (`vsia/agent.py` line 87); the dashboard redacts it on display |
| `cited_sources` | JSON | | `recall:<campaign>` for each kept match plus `complaint:<odi>` | no | |
| `provider` | String(32) | | `ollama`, `anthropic`, `openai` or `heuristic` | no | |
| `model` | String(64) | | Model id, for example `qwen2.5:3b` | no | |
| `prompt_version` | String(16) | | `triage-v1` (`vsia.agent.PROMPT_VERSION`, file `src/vsia/prompts/triage_v1.md`) | no | |
| `latency_ms` | Integer | | End-to-end triage latency in milliseconds (redaction to validation) | no | |
| `cost_usd` | Float | | LLM cost of this triage from `vsia.llm.price` | no | 0 for Ollama and heuristic |
| `created_at` | DateTime | default utcnow | Record time | no | |

## review_queue

Pending and resolved human review items. A row is created only when `route = review` and the caller
allows enqueueing (evaluation runs do not, ADR-0064).

- **Producers:** `vsia.agent.save()` (insert, `status = pending`); `vsia.review.decide()` (update to
  `accepted` or `corrected`, sets `resolved_at`).
- **Consumers:** `vsia.review.pending` (API `GET /review/pending`, n8n workflow 02 backlog count, dashboard
  review page), `vsia.review.stats`, `app/data.py`.

| Column | Type | Key / index | Description | PII | Notes |
|---|---|---|---|---|---|
| `id` | Integer | primary key, autoincrement | Queue item id | no | |
| `odi_number` | Integer | not null, index | Complaint under review | no | |
| `triage_record_id` | Integer | index | The `triage_records.id` that was routed to review | no | |
| `status` | String(16) | default `pending`, index | `pending`, `accepted` or `corrected` | no | |
| `reason` | Text | | `review_reasons` joined with `; `: low confidence (with score and threshold), possible prompt injection, or LLM failure | no | machine-generated text |
| `created_at` | DateTime | default utcnow | Enqueue time | no | |
| `resolved_at` | DateTime | | Decision time | no | |

## labels

Labelled data reused by evaluation: human review decisions, silver gold-set labels and (later) hand
labels.

- **Producers:** `vsia.review.decide()` (`source = review`); `eval/build_gold.py` `write_labels_table`
  (`source = gold_silver`, replaces all earlier silver rows); `eval/build_gold.py --promote`
  (`source = gold_hand`).
- **Consumers:** evaluation and future calibrator refits (ADR-0061 "Revisit when"), dashboard review stats.

| Column | Type | Key / index | Description | PII | Notes |
|---|---|---|---|---|---|
| `id` | Integer | primary key, autoincrement | Label id | no | |
| `odi_number` | Integer | not null, index | Complaint labelled | no | |
| `component` | String(64) | | Label component (taxonomy value) | no | |
| `severity` | String(4) | | Label severity `S1` to `S4` | no | |
| `recall_campaigns` | JSON | | Campaigns judged to match | no | |
| `source` | String(32) | | `review`, `gold_hand` or `gold_silver` | no | 500 `gold_silver` rows today |
| `reviewer` | String(64) | | Reviewer name typed into the review form (free text, ADR-0073), `owner` by default for promotions, or `rules:silver-v1` for silver rows | yes | a staff member's name when a person reviews |
| `note` | Text | | Reviewer note (free text); for silver rows a JSON string with split, components_all, severity_source, needs_hand_review and candidate_recalls | possible | reviewer free text |
| `created_at` | DateTime | default utcnow | Label time | no | |

## llm_calls

One row per `vsia.llm.complete_json()` call (after up to one repair retry, ADR-0007). Metadata only:
prompt and reply text are never stored (AGENTS.md rule 4).

- **Producer:** `vsia.db.log_llm_call`, called by `vsia.llm.complete_json`. Logging never raises. The
  n8n-native workflow 05 calls Anthropic directly and does not write here.
- **Consumers:** `vsia.observability.cost_latency_summary` and `cost_per_1000` (dashboard, cost model),
  `docs/operations/runbooks/cost-spike.md`.

| Column | Type | Key / index | Description | PII | Notes |
|---|---|---|---|---|---|
| `id` | Integer | primary key, autoincrement | Call id | no | |
| `provider` | String(32) | index | `ollama`, `anthropic` or `openai` | no | |
| `model` | String(64) | index | Model id | no | |
| `purpose` | String(32) | index | `triage`, `rag_plan`, `rag_answer`, `recall_extraction` (also `smoke` in the current database) | no | |
| `input_tokens` | Integer | | Input tokens summed over attempts | no | |
| `output_tokens` | Integer | | Output tokens summed over attempts | no | |
| `cost_usd` | Float | | Tokens times the dated price table in `config/settings.yaml` | no | |
| `latency_ms` | Integer | | Wall time across attempts | no | |
| `ok` | Boolean | | True when a reply validated | no | |
| `error` | Text | | Exception or validation message (up to about 400 characters) | possible | a Pydantic validation message can echo fragments of the model's reply |
| `prompt_version` | String(16) | | `triage-v1`, `rag-v1` or `recall-extract-v1` | no | |
| `ref_id` | String(64) | | Business key: ODI number for triage, campaign number for extraction, null for chat | no | join key to `triage_records.odi_number` |
| `created_at` | DateTime | default utcnow, index | Call time | no | |

## ingestion_runs

One row per ingestion run with fetched, inserted, duplicate and filtered counts (FR-1 acceptance
criterion; ADR-0004 point 7).

- **Producer:** `vsia.ingest.ingest_complaints` and `vsia.ingest.ingest_recalls`.
- **Consumers:** dashboard overview (last run), `docs/operations/runbooks/ingestion-failed.md`, API
  `POST /ingest/daily` response (counts without `details`), n8n workflow 01 (`ok` check).

| Column | Type | Key / index | Description | PII | Notes |
|---|---|---|---|---|---|
| `id` | Integer | primary key, autoincrement | Run id | no | |
| `kind` | String(32) | | `complaints_api`, `complaints_backfill` or `recalls` | no | |
| `started_at` | DateTime | | Run start (UTC) | no | |
| `finished_at` | DateTime | | Run end (UTC) | no | |
| `rows_fetched` | Integer | | Rows returned by the NHTSA API | no | |
| `rows_inserted` | Integer | | New rows written | no | |
| `rows_skipped_duplicate` | Integer | | Rows skipped because the key already existed | no | |
| `rows_filtered` | Integer | | Rows dropped by segment rules (empty summary, excluded model, filed before `filed_from`) | no | always 0 for recalls |
| `ok` | Boolean | | False when the complaint loop raised | no | the recall run always records true |
| `error` | Text | | `repr()` of the exception | no | |
| `details` | JSON | | Complaints: `{"per_vehicle": {"MAKE\|MODEL\|YEAR": rows fetched}}`; recalls: `{}` | no | |

## forecasts

Weekly forecasts per component written by the champion model: out-of-sample weeks after the champion's
training window (`is_holdout = true`, with actuals) and 4 future weeks (`is_holdout = false`).

- **Producer:** `pipelines/forecast.py cmd_detect` (`python -m pipelines.forecast detect` or `all`, API
  `POST /forecast/run`, n8n workflow 03). Rows for the weeks being written are deleted first, so each week
  keeps only the latest run.
- **Consumers:** dashboard trends page and overview KPI, `scripts/export_demo_snapshot.py`.

| Column | Type | Key / index | Description | PII | Notes |
|---|---|---|---|---|---|
| `id` | Integer | primary key, autoincrement | Row id | no | |
| `run_id` | String(64) | index | MLflow run id of the champion model version (`vsia-complaint-forecaster@champion`) | no | lineage key into MLflow |
| `component` | String(64) | index | Canonical component; components with fewer than `forecast.min_weekly_total` (30) complaints are pooled into `OTHER` | no | |
| `week` | Date | index | Week start (Monday, `freq: W-MON`) | no | |
| `actual` | Float | | Complaints filed that week; null for future weeks | no | |
| `forecast` | Float | | Point forecast | no | |
| `lower` | Float | | Lower bound of the prediction interval (`forecast.spike_interval`, 0.90) | no | |
| `upper` | Float | | Upper bound of the prediction interval | no | |
| `model_name` | String(64) | | `<model family>@v<registry version>`, for example `gbm@v3` | no | |
| `is_holdout` | Boolean | | True for evaluated weeks with actuals, false for future weeks | no | |
| `created_at` | DateTime | default utcnow | Write time | no | |

## spike_alerts

Component-weeks whose actual count is strictly above the interval upper bound and at least 3 complaints
(`pipelines/features.flag_spikes`, `MIN_ALERT_COUNT = 3`).

- **Producer:** `pipelines/forecast.py cmd_detect`; rows for the evaluated weeks are deleted first.
- **Consumers:** API `POST /forecast/run` response (n8n workflow 03 branches on it), dashboard trends page.

| Column | Type | Key / index | Description | PII | Notes |
|---|---|---|---|---|---|
| `id` | Integer | primary key, autoincrement | Row id | no | |
| `run_id` | String(64) | index | MLflow run id of the champion | no | |
| `component` | String(64) | | Component | no | |
| `week` | Date | | Week start | no | |
| `actual` | Float | | Observed count | no | |
| `upper` | Float | | Interval upper bound | no | |
| `ratio` | Float | | `actual / max(upper, 1)` | no | |
| `created_at` | DateTime | default utcnow | Write time | no | |

The `current` flag (alert in the last 4 complete weeks) and `recalls_near` (recall reported within 28 days)
are computed in memory and returned by the API, but are not stored in this table.

## eval_runs

One row per scored evaluation (`eval/run_eval.py score`).

- **Producer:** `eval/run_eval.py score` (also the last step of `all`).
- **Consumers:** dashboard evaluation page, `scripts/export_demo_snapshot.py`.

| Column | Type | Key / index | Description | PII | Notes |
|---|---|---|---|---|---|
| `id` | Integer | primary key, autoincrement | Row id | no | |
| `run_id` | String(64) | index | `eval-<split>-<provider>-<unix seconds>` | no | different from the `run_id` written to `triage_records` by the predict step |
| `provider` | String(32) | | Provider evaluated | no | |
| `model` | String(64) | | Model evaluated | no | |
| `metrics` | JSON | | The whole run dict: provider, model, split, prompt_version, `metrics` (component accuracy primary and any-label, macro-F1, field accuracy, severity agreement, S1 precision and recall of the raw LLM severity, auto-route rate and accuracy, threshold, recall@5, match hit rate and precision, failure rate, latency median and p95, cost per 1,000), per-class accuracy and `mlflow_run_id` when MLflow logging succeeded | no | |
| `created_at` | DateTime | default utcnow | Write time | no | |

---

## File-based datasets

These are not tables, but they are inputs or outputs of the same jobs and appear in the
[lineage](lineage.md) graph.

| Path | Producer | Content | PII |
|---|---|---|---|
| `data/raw/scoped_vehicles.json` | `vsia.ingest.resolve_vehicles` | Resolved (make, model, model year) query list; 145 entries today | no |
| `data/raw/nhtsa_model_strings.json` | build-time verification | NHTSA model strings seen during verification | no |
| `data/docs/manifest.json` | `scripts/fetch_recall_docs.py` | One entry per PDF: campaign, doc type, URL, file, bytes, SHA-256, load date, component, complaint volume, download time; 150 entries, 33,171,079 bytes | no |
| `data/docs/pdf/*.pdf` | `scripts/fetch_recall_docs.py` | Raw recall PDFs (unredacted public documents) | yes (sample names and addresses in owner letters) |
| `data/index/<namespace>/` | `scripts/build_index.py` (local store) | `vectors.npy` (768-d), `meta.jsonl` (id, redacted text, metadata), `info.json` | possible (redacted text) |
| `data/gold/gold_set.jsonl`, `calibration_set.jsonl`, `splits.json`, `build_summary.json`, `gold_set_review.csv` | `eval/build_gold.py` | Silver labels and splits; see [gold set datasheet](datasheet-gold-set.md) | possible (redacted narratives) |
| `data/models/component_clf.joblib`, `component_clf_metrics.json` | `python -m vsia.classifier train` | TF-IDF baseline classifier (`tfidf-logreg-v1`, trained 2026-10-19 18:20 UTC; git-ignored); results in `docs/evaluation/baseline-classifier.md` | no |
| `data/models/confidence_calibrator_<provider>.joblib`, `routing_<provider>.json` | `eval/run_eval.py calibrate` | Calibrator and tuned threshold per provider (not present at the time of writing) | no |
| `data/eval/<split>_<provider>.jsonl`, `score_<split>_<provider>.json` | `eval/run_eval.py` | Stored predictions and scores (not present at the time of writing) | possible (model output) |
| `data/mlflow.db`, `data/mlartifacts/` | `pipelines/forecast.py`, `eval/run_eval.py` | MLflow tracking store and artifacts | no |
| `app/demo_data/*.parquet`, `manifest.json` | `scripts/export_demo_snapshot.py` | Redacted read-only dashboard snapshot; the hosted demo's fallback when no data bundle is installed (ADR-0072, ADR-0089) | no (redacted) |
