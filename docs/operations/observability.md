# Observability

What the system records today, how those records map to the OpenTelemetry GenAI semantic conventions,
where to look, and which alerts exist or are proposed. Code: `src/vsia/llm.py`, `src/vsia/db.py`,
`src/vsia/observability.py`, `src/vsia/agent.py`, `src/vsia/ingest.py`, `eval/run_eval.py`,
`pipelines/forecast.py`.

Principle: log metadata, never content. Prompt text, completion text and complaint narratives are not
logged (AGENTS.md rule 4, OWASP LLM02). Complaint text is redacted before it reaches an LLM, an embedding
model or a log line.

## 1. What is recorded today

Everything below is a database row or an MLflow run. There is no metrics backend, trace collector or
log aggregator; the stack relies on SQL over these tables, the dashboard and container logs.

### 1.1 LLM calls: `llm_calls`

One row per `vsia.llm.complete_json()` call, written by `vsia.db.log_llm_call()`. Logging never raises:
a failed insert is swallowed so that it cannot break triage.

| Column | Meaning |
|---|---|
| `id` | auto-increment |
| `provider` | `ollama`, `anthropic` or `openai` |
| `model` | model id requested |
| `purpose` | `triage`, `rag_plan`, `rag_answer`, `recall_extraction` (and `smoke` for manual tests) |
| `input_tokens`, `output_tokens` | provider-reported usage, summed over the validation retry when there is one |
| `cost_usd` | `input_tokens / 1e6 * price_in + output_tokens / 1e6 * price_out` from `config/settings.yaml`, rounded to 8 decimals |
| `latency_ms` | wall time of the whole call including HTTP retries and the validation retry |
| `ok` | true if a schema-valid object was returned |
| `error` | exception text or `invalid output (attempt N): ...` (truncated), never the prompt |
| `prompt_version` | for example `triage-v1` |
| `ref_id` | the business key, for triage the complaint `odi_number` |
| `created_at` | UTC timestamp, indexed |

State on 2026-10-19 (read-only query on `data/vsia.db`): three rows, all Ollama `qwen2.5:3b`: two `smoke`
calls (one failed) and one `triage` call that succeeded with 2,057 input tokens, 326 output tokens and
41,497 ms latency.

### 1.2 Triage decisions: `triage_records`

One row per triage, with `run_id`, `provider`, `model`, `prompt_version`, `schema_version`, `component`,
`severity`, `recall_campaigns`, `confidence`, `route`, `latency_ms` (end to end), `cost_usd` and the
`confidence_signals` JSON. The signals are the per-decision audit trail: classifier probabilities,
retrieval scores, the ranked campaign list, the LLM's raw severity, whether the severity rule overrode it,
dropped citations, off-taxonomy labels, LLM errors, the confidence method and the review reasons. The full
list is in the [review workflow](../hitl/review-workflow.md#31-signals). Empty on 2026-10-19.

### 1.3 Review: `review_queue`, `labels`

`review_queue.created_at`, `resolved_at` and `status` give backlog size, age and correction rate.
`labels` holds every decision. See the [review workflow](../hitl/review-workflow.md).

### 1.4 Ingestion: `ingestion_runs`

One row per ingestion run from `vsia.ingest`: `kind` (`complaints_api`, `complaints_backfill`,
`recalls`), `started_at`, `finished_at`, `rows_fetched`, `rows_inserted`, `rows_skipped_duplicate`,
`rows_filtered`, `ok`, `error` and a `details` JSON (per-vehicle counts for complaints). On 2026-10-19 it
has two successful `complaints_api` runs and one successful `recalls` run.

### 1.5 Evaluation and forecasting

| Store | Written by | Content |
|---|---|---|
| `eval_runs` table | `eval/run_eval.py score` | provider, model and the full run dict (metrics, per-class table) |
| MLflow experiment `vsia-triage-eval` | `eval/run_eval.py score` | params provider, model, split, prompt version; every numeric metric; `eval_run.json` |
| MLflow experiment `vsia-forecast` | `pipelines/forecast.py train` | parent run per training with the data fingerprint, nested run per candidate model with metrics, per-component metrics and artifacts; registered model `vsia-complaint-forecaster` with alias `champion` |
| `forecasts`, `spike_alerts` tables | `pipelines/forecast.py detect` | point forecast, interval, actual, model name; alerts with ratio |

On 2026-10-19 `eval_runs`, `forecasts` and `spike_alerts` are empty; `vsia-forecast` has one parent run
(FAILED), five FINISHED candidate runs and one FAILED candidate run, and no registered model (see the
[backtest report](../models/backtest-report.md)).

### 1.6 Spans in logs: `vsia.observability.timed()`

`timed(operation, **attributes)` times a block and writes one INFO log line `span <operation> {json}` with
`gen_ai.*` attribute names, a span id, `duration_ms` and `status`. Text-bearing keys are replaced with
`[omitted]`, other strings pass through `redact()`. It is tested (`tests/test_llm_gateway.py`) but **not
yet called** from the agent, retrieval or tools, so no span lines are produced in normal operation.
`llm_call_attributes(call)` maps an `LLMCall` to the same names; it is also only used in tests.

### 1.7 Reporting helpers

`vsia.observability.cost_latency_summary(since=None)` groups `llm_calls` by provider, model and purpose:
calls, errors, error rate, total cost, cost per 1,000 calls, p50 and p95 latency, mean tokens. Failed
calls count towards cost and latency. `cost_per_1000(provider, model, purpose)` returns the measured
cost of 1,000 calls, or `None` when nothing is logged (an unmeasured cost is not zero).

## 2. Mapping to OpenTelemetry GenAI semantic conventions

Since semantic conventions v1.42.0 (2026-06-12) the `gen_ai.*` conventions live in the
`open-telemetry/semantic-conventions-genai` repository, with Development stability (docs/research/01,
section 9). This mapping follows that repository's attribute registry as read on 2026-10-18. Pin the
convention version when an exporter is added, because names may still change.

| OTel attribute | VSIA source today | Status |
|---|---|---|
| `gen_ai.operation.name` | constant `chat` in `llm_call_attributes`; the operation argument of `timed()` | Mapped |
| `gen_ai.provider.name` | `llm_calls.provider` | Mapped |
| `gen_ai.system` | same value as `gen_ai.provider.name` | Older name, kept for older backends |
| `gen_ai.request.model` | `llm_calls.model` | Mapped |
| `gen_ai.response.model` | not captured; providers return it but `vsia.llm` discards it | Gap: needed to audit silent model upgrades behind an alias |
| `gen_ai.usage.input_tokens` | `llm_calls.input_tokens` (Ollama `prompt_eval_count`) | Mapped. Sum over two attempts when a validation retry happened |
| `gen_ai.usage.output_tokens` | `llm_calls.output_tokens` (Ollama `eval_count`) | Mapped |
| `gen_ai.prompt.name` | not set; `llm_calls.purpose` is the closest value | Gap: set it to the prompt file name, for example `triage_v1` |
| `gen_ai.prompt.version` | `llm_calls.prompt_version` | Mapped |
| `gen_ai.agent.name` | not set | Gap: one agent, `vsia-triage` |
| `gen_ai.tool.name` | not set in production; `recall_lookup` and `recall_search` are the tools | Gap: wrap `vsia.tools` calls in `timed()` |
| `gen_ai.data_source.id` | not set; retrieval namespaces are `recalls`, `recall_docs`, `tsbs`, `complaints` | Gap |
| `gen_ai.retrieval.top_k` | `retrieval.top_k` in settings (5) | Gap: not recorded per call |
| `gen_ai.retrieval.query.text`, `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions`, `gen_ai.tool.call.arguments`, `gen_ai.tool.call.result` | never recorded | Deliberate: `timed()` replaces these with `[omitted]` |
| span duration | `llm_calls.latency_ms`, `triage_records.latency_ms`, `duration_ms` in span logs | Mapped as attributes, not as real span timing |
| error | `llm_calls.ok` and `error`; `status` and `error.type` in span logs | `error.type` follows OTel; `status` is a VSIA key |
| `vsia.purpose`, `vsia.cost_usd`, `vsia.ref_id` | `llm_calls` columns | Project namespace; cost has no OTel attribute |

Request parameters (`temperature` 0.0, `max_output_tokens` 700 from settings) are fixed per deployment and
not recorded per call.

Moving to real OTel traces later is a handler change, not a schema change: emit one span per
`complete_json()` call with the mapped attributes, one per tool call and one per retrieval, under a parent
span per triage keyed by `ref_id`.

## 3. Where to look

| Question | Place |
|---|---|
| Is the system up and which provider and threshold are live | `GET /health` (DB ping, provider, model, vector store, threshold) and Docker health checks on the VM |
| Ingestion, triage volume, auto-route share, pending reviews, cost to date | Dashboard Overview page |
| Individual decisions and their signals | Dashboard Triage page |
| Review backlog and correction rate | Dashboard Human review page |
| Volume trends, forecasts, spike alerts | Dashboard Trends page |
| Eval metrics, routing threshold curve, LLM cost and latency by provider and purpose | Dashboard Evaluation page |
| Forecast backtests, model versions, champion alias | MLflow UI (on the VM only through an SSH tunnel to `127.0.0.1:5000`, ADR-0081) |
| Workflow executions and failures | n8n execution history |
| Errors in the API | `docker compose logs vsia-api` (metadata only) |

Page contents and data sources are documented in [dashboard.md](../architecture/dashboard.md).

## 4. Alerts

### 4.1 Existing

| Alert | Mechanism | Default |
|---|---|---|
| Daily ingestion or triage failed | n8n workflow 01 failure branch, then the execution is marked failed | Notify node disabled until `VSIA_NOTIFY_WEBHOOK_URL` is set |
| Review backlog | n8n workflow 02, hourly, `GET /review/pending` count above `VSIA_REVIEW_BACKLOG_THRESHOLD` | 25 |
| Forecast spike alerts | n8n workflow 03 after `POST /forecast/run`, when the response lists alerts | Notify node disabled until configured |
| Container health | Docker health checks restart nothing by themselves; `docker compose ps` shows `unhealthy` | |

### 4.2 Proposed

Thresholds are starting points; each links to the runbook that handles it. The queries are portable SQL
over the existing tables and can run from an n8n schedule.

| Alert | Condition | Runbook |
|---|---|---|
| LLM error burst | `llm_calls` in the last hour with at least 10 calls and error rate above 20% for one provider | [LLM provider outage](runbooks/llm-provider-outage.md) |
| Schema failure drift | share of `llm_calls.error` starting with `invalid output` above 5% over 24 hours for `triage` | [LLM provider outage](runbooks/llm-provider-outage.md) (validation errors row) |
| Daily cost | `sum(cost_usd)` for the current UTC day above twice the daily budget in the [cost model](cost-model.md) | [Cost spike](runbooks/cost-spike.md) |
| Ingestion stale | no `ingestion_runs` row with `kind = 'complaints_api'` and `ok` true in the last 26 hours | [Ingestion failed](runbooks/ingestion-failed.md) |
| Review share jump | daily share of `route = 'review'` more than 20 points above its 14-day median | [Review backlog](runbooks/review-backlog.md) |
| Confidence method fallback | any production triage record with `confidence_method = 'fallback_weights'` for a provider that has a routing file | [Review backlog](runbooks/review-backlog.md) (missing threshold row); see the deployment gap in the [review workflow](../hitl/review-workflow.md#11-known-gaps) |
| Forecast job missed | no `forecasts` row with `created_at` in the last 8 days | [Incident playbook](incident-playbook.md) |
| S1 review age | any pending item with `triage_records.severity = 'S1'` older than 1 business day | [Review backlog](runbooks/review-backlog.md) |

## 5. Gaps

1. `timed()` is not wired into the agent, tools or retrieval, so there is no per-step latency breakdown.
2. `gen_ai.response.model` is not captured.
3. `triage_records.cost_usd` is 0 when the LLM call failed, while `llm_calls` records the cost of the
   failed attempts. Cost totals from the two tables differ by that amount; use `llm_calls` for spend.
4. `/health` checks the database only; it does not check the LLM provider, the vector store, or that the
   classifier and calibrator files are present.
5. There is no external uptime probe, so API availability is not measured (see [SLOs](slos.md)).
