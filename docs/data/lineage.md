# Data lineage

This page describes VSIA's lineage in OpenLineage terms (datasets, jobs, runs and facets), maps every
public source to the tables built from it, and gives the queries that trace a triage record or a forecast
back to the raw NHTSA data, the prompt version and the model run that produced it.

VSIA does not emit OpenLineage events today. The identifiers that make tracing possible already exist in
the tables and in MLflow; this page names them in OpenLineage vocabulary so that adding an emitter later
(for example from the n8n workflows or the API) is a mapping exercise, not a redesign. Known gaps, where
the stored identifiers are not enough, are listed at the end.

Related: [data dictionary](data-dictionary.md) (columns), [data flow](../architecture/data-flow.md)
(writers, readers, redaction), [observability](../operations/observability.md) (logs and spans).

## OpenLineage model applied to VSIA

OpenLineage describes lineage as **jobs** that run as **runs** and read and write **datasets**; extra
metadata is attached as **facets** (OpenLineage specification, as summarised in
`docs/research/01_documentation_process_research.md` section 4).

### Dataset namespaces

| Namespace (proposed) | Datasets |
|---|---|
| `https://api.nhtsa.gov` | `complaints/complaintsByVehicle`, `recalls/recallsByVehicle`, `products/vehicle/models`, `safetyIssues/byNhtsaId` |
| `https://static.nhtsa.gov` | Recall PDFs (`RCLRPT`, `RCONL`) |
| `sqlite://data/vsia.db` (laptop) or `postgres://<vm>/vsia` (VM) | The 11 tables in the [data dictionary](data-dictionary.md) |
| `file://data` | `raw/scoped_vehicles.json`, `docs/manifest.json`, `docs/pdf/*`, `gold/*`, `models/*`, `eval/*`, `index/<namespace>/*` |
| `pinecone://<index>` | Namespaces `recalls`, `recall_docs`, `complaints` (VM only) |
| `mlflow://data/mlflow.db` | Experiments `vsia-forecast`, `vsia-triage-eval`; registered model `vsia-complaint-forecaster` |

### Jobs, runs and the run identifier each one already has

Job ids J1 to J14 match the [data flow](../architecture/data-flow.md#jobs) page.

| Job | OpenLineage job name (proposed) | Inputs | Outputs | Run identifier stored today | Useful facets available |
|---|---|---|---|---|---|
| J1 ingest complaints | `vsia.ingest.complaints` | NHTSA complaints API, `scoped_vehicles.json`, `complaints` (seen ids) | `complaints`, `ingestion_runs` | `ingestion_runs.id` with `started_at`, `finished_at` | rows fetched, inserted, duplicate, filtered; `details.per_vehicle` |
| J2 ingest recalls | `vsia.ingest.recalls` | NHTSA recalls API, `complaints` (vehicle list) | `recalls`, `ingestion_runs` | `ingestion_runs.id` | counts |
| J3 fetch recall docs | `vsia.docs.fetch` | `complaints`, `recalls`, safetyIssues API, static PDFs | `data/docs/` | none (`downloaded_at` per manifest entry, `fetch_log`) | SHA-256 and bytes per file |
| J4 parse documents | `vsia.documents.process` | `data/docs/` | `recall_documents`, `llm_calls` (fallback only) | none (`recall_documents.parsed_at`) | parser, pages, extraction method, validity |
| J5 build index | `vsia.index.build` | `recalls`, `recall_documents`, `complaints` | `data/index/*` or Pinecone | `info.json` `updated_at` timestamp per namespace | embedding model, dimension, record count |
| J6 build gold | `vsia.eval.build_gold` | `complaints`, `recalls` | `data/gold/*`, `labels` | `splits.json` `meta.created_at`, `build_summary.json` `built_at` | `splits-v1`, seed 42, `silver-v1` rules, class counts |
| J7 train classifier | `vsia.classifier.train` | `complaints`, `data/gold/splits.json` | `data/models/component_clf*` | none (metrics file timestamp) | metrics file |
| J8 triage | `vsia.agent.triage` | `complaints`, `recalls`, index, `data/models/*` | `triage_records`, `review_queue`, `llm_calls` | `triage_records.run_id` | provider, model, `prompt_version`, `schema_version`, confidence signals |
| J9 evaluation | `vsia.eval.run` | `data/gold/*`, J8 outputs | `data/eval/*`, `data/models/routing_*`, `eval_runs`, MLflow, reports | `eval-<split>-<provider>-...` in `triage_records.run_id`; a different `eval_runs.run_id`; `metrics.mlflow_run_id` | metrics, `prompt_version` |
| J10 human review | `vsia.review.decide` | `review_queue`, `triage_records` | `review_queue`, `labels` | none (`labels.created_at`, `review_queue.resolved_at`) | reviewer |
| J11 RAG chat | `vsia.rag.answer` | index, `complaints` | `llm_calls` | none | `prompt_version` `rag-v1` |
| J12 forecast | `vsia.forecast.train`, `vsia.forecast.detect` | `complaints`, `recalls` | MLflow runs and registry, `forecasts`, `spike_alerts`, plots | MLflow run id (`forecasts.run_id`, `spike_alerts.run_id`) | `data_fingerprint`, `pipeline_version`, parameters, metrics |
| J13 demo snapshot | `vsia.demo.export` | dashboard tables | `app/demo_data/*` | `manifest.json` `exported_at` | row counts, bytes |
| J14 native n8n triage | `n8n.vsia-triage-native` | Postgres `complaints`, NHTSA recalls API, `/search` | `triage_records` | `triage_records.run_id = n8n-native-<execution id>` | n8n execution log |

## Source-to-table mapping

| Public source | Endpoint or file | Loaded by | Table or file | Key | Transformations |
|---|---|---|---|---|---|
| NHTSA vehicle model list | `/products/vehicle/models?issueType=c` | J1 `resolve_vehicles` (first run, then cached) | `data/raw/scoped_vehicles.json` (145 entries) | make, model, model year | regex match against `segment.vehicles` patterns in `config/settings.yaml` |
| NHTSA complaints | `/complaints/complaintsByVehicle` | J1 | `complaints` | `odi_number` | `normalize_complaint`: upper-case make, canonical model from the complaint's product record, dates parsed, `summary` stripped; drop empty summaries, `exclude_models` and filings before `segment.filed_from` (2022-01-01); `component_primary` derived from `components_raw` |
| NHTSA recalls | `/recalls/recallsByVehicle` | J2 | `recalls` | campaign number x make x model x model year | `normalize_recall`: DD/MM/YYYY dates, `component_primary` derived |
| NHTSA safety issue documents | `/safetyIssues/byNhtsaId` (unofficial) then `static.nhtsa.gov` | J3 | `data/docs/manifest.json`, `data/docs/pdf/` | source URL, SHA-256 | campaign selection by complaint volume, round-robin by component; latest Part 573 report and earliest owner letter; size caps |
| Recall PDFs | `data/docs/pdf/*.pdf` | J4 | `recall_documents` | `source_url` | pypdf or OCR or LlamaParse to markdown with page markers; redaction; rules extraction, LLM fallback |
| Derived | `recalls`, `recall_documents`, `complaints` | J5 | index namespaces | record id (campaign x vehicle, chunk id, ODI) | `vehicle_keys` `MAKE\|MODELFAMILY\|YEAR`; 800-token chunks with 100 overlap; complaint narratives redacted |
| Derived | `complaints`, `recalls` | J6 | `data/gold/*`, `labels` (`gold_silver`) | `odi_number` | silver labels from NHTSA coding and rules (ADR-0005), stratified split |

## Tracing procedures

All queries are read-only. On the laptop run them with `sqlite3 -readonly data/vsia.db`; on the VM use
`psql` against the `vsia` database (the SQL is portable apart from the date functions).

### 1. From a triage record back to the raw complaint and its ingestion run

```sql
-- the triage record and its provenance
SELECT id, odi_number, run_id, provider, model, prompt_version, schema_version,
       confidence, route, created_at
FROM triage_records WHERE id = :triage_id;

-- the raw source row (NHTSA ODI number) and its load time
SELECT odi_number, make, model, model_year, date_filed, components_raw, component_primary,
       ingested_at, source
FROM complaints WHERE odi_number = :odi;

-- the ingestion run whose time window contains the load time
SELECT id, kind, started_at, finished_at, rows_inserted, ok
FROM ingestion_runs
WHERE kind LIKE 'complaints%'
  AND :ingested_at BETWEEN started_at AND finished_at;
```

The ODI number is NHTSA's own key, so the source record can also be re-fetched from the public API or
looked up on nhtsa.gov.

### 2. From a triage record to its LLM call

`llm_calls` has no foreign key to `triage_records`. The call is identified by the business key plus
provider, model, prompt version and a time window: the gateway writes the call row before
`triage_records.created_at`, and within the record's `latency_ms`.

```sql
SELECT l.id, l.provider, l.model, l.prompt_version, l.input_tokens, l.output_tokens,
       l.cost_usd, l.latency_ms, l.ok, l.error, l.created_at
FROM llm_calls l
JOIN triage_records t
  ON l.ref_id = CAST(t.odi_number AS TEXT)
 AND l.provider = t.provider AND l.model = t.model
 AND l.prompt_version = t.prompt_version
WHERE t.id = :triage_id
  AND l.purpose = 'triage'
  AND l.created_at <= t.created_at
ORDER BY l.created_at DESC
LIMIT 1;
```

Records produced by provider `heuristic` or by n8n workflow 05 have no matching `llm_calls` row. When the
LLM failed and the record fell back to the classifier, the matching row exists with `ok = false` and the
error message.

### 3. From a triage record to the exact prompt and model inputs

| Input | How to recover it |
|---|---|
| System prompt | `prompt_version` (`triage-v1`) names `src/vsia/prompts/triage_v1.md`; the glossary and rubric come from `config/component_glossary.yaml` and `config/settings.yaml` at the same git revision |
| Complaint text sent | `redact(complaints.summary)` with the redactor at the same git revision (redaction is deterministic and idempotent) |
| Candidate recalls shown | `confidence_signals.candidates` (campaign numbers in prompt order) |
| Retrieval ranking | `confidence_signals.retrieval_ranked`, `retrieval_top_score` |
| Classifier signals | `confidence_signals.clf_*`, `agree` |
| Threshold used | not stored on the record; it is `data/models/routing_<provider>.json` (`fitted_at`) or the configured default at that time |

### 4. From a review decision to the label and back

```sql
SELECT q.id AS queue_id, q.status, q.reason, q.created_at, q.resolved_at,
       t.id AS triage_id, t.run_id, t.component AS model_component, t.severity AS model_severity
FROM review_queue q JOIN triage_records t ON t.id = q.triage_record_id
WHERE q.odi_number = :odi;

SELECT id, component, severity, recall_campaigns, source, reviewer, created_at
FROM labels WHERE odi_number = :odi AND source = 'review';
```

`labels` stores no `queue_id` or `triage_record_id`; a label is matched to its queue item by
`odi_number` and `labels.created_at` close to `review_queue.resolved_at` (both are written in the same
transaction by `vsia.review.decide`).

### 5. From an evaluation run to its predictions and MLflow run

1. `eval_runs.metrics` holds `provider`, `model`, `split`, `prompt_version` and, when MLflow logging
   succeeded, `mlflow_run_id` (experiment `vsia-triage-eval`).
2. The predictions are in `data/eval/<split>_<provider>.jsonl`, one triage record per ODI.
3. The same predictions are in `triage_records` with `run_id LIKE 'eval-<split>-<provider>-%'`. The
   `eval_runs.run_id` (`eval-<split>-<provider>-<unix seconds>`) is generated separately and does not
   match those ids; link them by split, provider and time.
4. The gold labels come from `data/gold/` built with `splits-v1` and `silver-v1`
   ([gold set datasheet](datasheet-gold-set.md)).

### 6. From a forecast or spike alert back to the model, the data and the complaints

```sql
SELECT run_id, model_name, component, week, actual, forecast, lower, upper, is_holdout, created_at
FROM forecasts WHERE component = :component AND week = :week;
```

1. `forecasts.run_id` is the MLflow run id of the champion candidate run; `model_name` is
   `<family>@v<registry version>`. In MLflow, that run carries tags `data_fingerprint`, `model_family`,
   `kind = candidate` and its parent `train-<timestamp>` run carries the panel parameters (`freq`,
   `holdout_weeks`, `min_weekly_total`, `interval`, `n_weeks`, `first_week`, `last_week`,
   `pooled_components`, `seed`).
2. The registered model version `vsia-complaint-forecaster` with alias `champion` repeats
   `data_fingerprint` and `run_id` as version tags.
3. The actual count for a component-week is reproducible from the source table:

```sql
-- SQLite; complaints filed in the W-MON week labelled :week (week start, Monday)
SELECT odi_number, date_filed, make, model, model_year
FROM complaints
WHERE component_primary = :component
  AND date_filed >= :week AND date_filed < date(:week, '+7 days');
```

For the pooled `OTHER` series, use the components listed in the parent run's `pooled_components`
parameter plus `component_primary = 'OTHER'`.

### Current state of the lineage stores (2026-10-19)

| Store | State |
|---|---|
| `ingestion_runs` | 3 runs: complaints run 1 (inserted 10,645), recalls run 2 (inserted 189, 218 duplicates), complaints run 3 (inserted 0, 13,367 duplicates, 819 filtered) |
| `triage_records`, `eval_runs` | empty |
| `forecasts`, `spike_alerts` | 320 forecast rows (240 out-of-sample, 80 for 4 future weeks) and 18 spike alerts, all with run id `98acce0d6c244ef9a75db49e2e9a1ea5` (`detect` with the champion) |
| `llm_calls` | 3 rows (two `smoke`, one `triage` with `qwen2.5:3b`, `triage-v1`, no matching triage record) |
| MLflow `vsia-forecast` | four parent runs. Three FAILED while logging a candidate model (`train-20261019T054635Z`, `train-20261019T182318Z`, `train-20261019T182351Z`; ADR-0055). `train-20261019T182422Z` (run `6c61abbf263f4e77b195d6d4d4d3c595`, `data_fingerprint` `ba0e4154ef3b8c37`, 249 weeks, 20 series after pooling 4 components, first week 2022-01-03, last week 2026-10-05, holdout from 2026-07-20) FINISHED with all seven candidate runs FINISHED. Registered model `vsia-complaint-forecaster` version 1 (READY, run `98acce0d6c244ef9a75db49e2e9a1ea5`, `glm_poisson`) holds the `champion` alias |
| MLflow `vsia-triage-eval` | no runs |
| `data/index/*/info.json` | `recalls` 407 records, `recall_docs` 352 records, `nomic-embed-text`, 768 dimensions; `complaints` namespace not yet written |

## Known lineage gaps

These are facts about the current code, recorded so that nobody assumes a trace that cannot be made.

1. **No run id on loaded rows.** `complaints` links to its run only through `ingested_at` falling inside a
   run's time window. Two overlapping runs (for example a manual run during the n8n run) cannot be told
   apart.
2. **Recalls have no timestamp at all.** `recalls` has neither `ingested_at` nor a run id, so a recall row
   cannot be tied to an ingestion run.
3. **Unlogged changes.** Run 1 inserted 10,645 complaints but the table holds 10,303: 342 rows were removed
   after loading by a step that is not in code and left no run row. `config/settings.yaml` explains the
   intent (models in `exclude_models` are "dropped after load"); the deletion itself is not recorded.
   Likewise, recall run 2 skipped 218 rows as duplicates, so an earlier recall load existed that has no
   `ingestion_runs` row.
4. **`ok` does not mean complete.** A per-vehicle fetch error is logged and skipped inside
   `ingest_complaints`; the run still records `ok = true`. The recall run always records `ok = true`.
5. **No foreign key from `llm_calls` to `triage_records`**, and none from `labels` to `review_queue` or
   `triage_records`; the joins above rely on business keys and time windows.
6. **Triage records do not store the threshold or calibrator version** used for routing, and
   `TriageRecord` (the JSON written to `data/eval/`) has no `run_id`.
7. **Evaluation run ids differ** between `triage_records` (predict step, one per predict invocation, so a
   resumed predict produces several) and `eval_runs` (score step).
8. **No git revision is recorded** in `triage_records`, `eval_runs` or the forecast MLflow runs
   (`mlflow.source.name` is a local path). `prompt_version` and `pipeline_version` stand in for it.
9. **Document jobs have no run record.** J3 and J4 write per-file timestamps but no run row; J5 writes
   only an `updated_at` timestamp per namespace.
10. **Workflow 05 bypasses the gateway**, so its triage records have no `llm_calls` row and no review
    queue entry (ADR-0075).
11. **Forecast plots and the registered run (resolved 2026-10-19).** `docs/models/forecast-plots/*.png`
    were rewritten at 18:24 UTC by the completed run `train-20261019T182422Z`, which also logs them to its
    parent run; they belong to the run that registered the current champion.
