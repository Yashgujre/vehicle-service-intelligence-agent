# Decision log

Architecture decision records (ADRs) for the Vehicle Service Intelligence Agent, in MADR style. Each record
states the context, the decision, the options considered, the trade-offs accepted, the consequences and a
"revisit when" trigger. Template: [0000-template.md](0000-template.md).

Rules:

- Numbers are never reused. A changed decision gets a new record that supersedes the old one; the old
  record stays, with its status set to "Superseded by ADR-XXXX".
- Number ranges belong to workstreams so parallel work does not collide (see `AGENTS.md`).
- This index lists every record in this folder as of 2026-10-19. Regenerate it whenever a record is added
  or its status changes.

## 0001-0019: cross-cutting and core

| ADR | Title | Component | Status |
|---|---|---|---|
| [0001](0001-python-service-owns-logic-n8n-orchestrates.md) | Keep triage logic in a Python service; n8n orchestrates and calls it | cross-cutting (agent, orchestration) | Accepted |
| [0002](0002-offline-first-provider-abstraction.md) | Offline-first: every external service has a local fallback behind one interface | cross-cutting | Accepted |
| [0003](0003-sqlite-local-postgres-on-vm.md) | One SQLAlchemy Core schema; SQLite on the laptop, Postgres on the VM | cross-cutting (storage) | Accepted |
| [0004](0004-segment-scope-and-ingestion-strategy.md) | Scope to EV and hybrid SUVs and pickups; ingest via the API with runtime model discovery | ingestion | Accepted |
| [0005](0005-component-taxonomy-and-label-leakage.md) | Use NHTSA's coded components as the taxonomy and as ground truth, never as model input | cross-cutting (data, evaluation) | Accepted |
| [0006](0006-model-selection.md) | Model choices: Claude Haiku 5.5, OpenAI gpt-6-luna, local qwen2.5:3b | LLM gateway | Accepted |
| [0007](0007-structured-output-and-validation.md) | Native structured output per provider, Pydantic re-validation, one repair retry | LLM gateway | Accepted |
| [0008](0008-no-local-docker-on-dev-laptop.md) | Run the stack natively on the laptop; Docker Compose targets the VM | infrastructure | Accepted |

## 0020-0029: guardrails and LLM gateway

| ADR | Title | Component | Status |
|---|---|---|---|
| [0020](0020-regex-pii-redaction-over-presidio-or-ner.md) | Redact PII with tested regular expressions, not Presidio or a named-entity model | guardrails | Accepted |
| [0021](0021-redact-before-llm-embedding-and-document-storage.md) | Redact at every use point (LLM, embedding, search, display, logs) and before storing parsed documents | guardrails, parsing, retrieval | Accepted |
| [0022](0022-keep-11-character-vin-prefix-redact-serial.md) | Keep the first 11 characters of a VIN and redact the serial | guardrails | Accepted |
| [0023](0023-flag-prompt-injection-for-review-do-not-block.md) | Flag suspected prompt injection and route to human review; never block or drop the record | guardrails, triage agent | Accepted |
| [0024](0024-wrap-untrusted-content-in-xml-style-tags.md) | Wrap untrusted content in XML-style tags after neutralising tag spoofing and chat-template tokens | guardrails, prompts | Accepted |
| [0025](0025-ground-citations-against-the-retrieved-set.md) | Accept a citation only if it is in the set of ids retrieved for that request | guardrails, triage agent, RAG chat | Accepted |
| [0026](0026-api-bearer-token-and-n8n-header-auth.md) | Protect the API with one bearer token and the n8n webhooks with header auth | guardrails (API edge), orchestration | Accepted |

## 0030-0039: document parsing and retrieval

| ADR | Title | Component | Status |
|---|---|---|---|
| [0030](0030-hybrid-retrieval-behind-a-store-interface.md) | Hybrid retrieval (dense + BM25, RRF) behind one store interface; local store by default, Pinecone optional | retrieval | Accepted |
| [0031](0031-pdf-parsing-llamaparse-optional-pypdf-and-ocr-default.md) | PDF parsing with pypdf by default, tesseract OCR for scans, LlamaParse when a key is present | document parsing | Accepted |
| [0032](0032-rules-first-extraction-llm-fallback.md) | Rule-based field extraction for fixed-layout forms; LLM extraction only as a fallback | document parsing | Accepted |
| [0033](0033-index-namespaces-and-record-design.md) | Index namespaces and record design; no ground-truth labels in the complaint index | retrieval | Accepted |

## 0040-0049: gold set, baselines and evaluation

| ADR | Title | Component | Status |
|---|---|---|---|
| [0040](0040-silver-labels-from-nhtsa-structured-fields.md) | Derive silver evaluation labels from NHTSA structured fields | evaluation | Accepted |
| [0041](0041-stratified-gold-calibration-and-train-splits.md) | Stratified gold set with per-class floor and cap, proportional calibration set, rest for training | evaluation | Accepted |
| [0042](0042-random-not-temporal-splits-with-temporal-check.md) | Draw gold and calibration splits at random across the filing window, and measure drift separately | evaluation | Accepted |
| [0043](0043-tfidf-logistic-regression-baseline-and-confidence-signal.md) | Use a TF-IDF and logistic regression classifier as the baseline and as a confidence signal | evaluation and baselines, agent | Accepted |
| [0044](0044-severity-silver-rules.md) | Silver severity from NHTSA incident flags first, then ordered keyword rules, default S3 | evaluation | Accepted |
| [0045](0045-recall-silver-labels-and-model-family-key.md) | Silver known-recall labels by vehicle, component and date, with a normalised model family key | evaluation | Accepted |
| [0046](0046-classifier-probability-calibration-by-dev-ece.md) | Choose the baseline classifier's probability calibration by top-label ECE on a dev slice | evaluation and baselines | Accepted |

## 0050-0059: forecasting and MLflow

| ADR | Title | Component | Status |
|---|---|---|---|
| [0050](0050-weekly-per-component-series-with-pooling.md) | Forecast weekly (Monday-start) complaint counts per component, pooling small components into OTHER | forecasting | Accepted |
| [0051](0051-global-models-with-statistical-baselines.md) | Register a global GLM or gradient-boosting model; keep per-series statistical methods as benchmarks | forecasting | Accepted |
| [0052](0052-rolling-origin-backtest-and-wape-selection.md) | Select the forecaster by mean validation WAPE over three rolling origins; report MASE and a 12-week holdout | forecasting | Accepted |
| [0053](0053-mlflow-registry-champion-alias-and-fingerprint-skip.md) | Serve the forecaster through an MLflow registry alias and skip retraining when the data fingerprint is unchanged | forecasting | Accepted |
| [0054](0054-spike-alert-rule-from-prediction-interval.md) | Flag a spike when the weekly count exceeds the 90% interval upper bound and is at least 3 | forecasting | Accepted |
| [0055](0055-cloudpickle-for-forecaster-artifacts.md) | Log the forecaster with cloudpickle, not skops, and load only models this pipeline wrote | forecasting | Accepted |

## 0060-0069: triage agent and human review

| ADR | Title | Component | Status |
|---|---|---|---|
| [0060](0060-fixed-workflow-agent-not-react-loop.md) | Triage is a fixed workflow with tool calls, not a free-running agent loop | triage agent | Accepted |
| [0061](0061-calibrated-confidence-per-provider.md) | Routing confidence is a calibrated composite score per provider, threshold tuned for auto-route accuracy | confidence and routing | Accepted |
| [0062](0062-severity-business-rule-override.md) | Owner-reported crash, fire, injury or death forces severity S1; the model's raw severity is kept and measured | triage agent | Accepted |
| [0063](0063-recall-match-grounding-rules.md) | Recall matches must be grounded in the candidate list and share a component with the triage result | triage agent, guardrails | Accepted |
| [0064](0064-evaluation-runs-isolated-from-review-queue.md) | Evaluation runs are tagged and never enter the human review queue | triage agent, evaluation | Accepted |
| [0065](0065-rag-chat-router-pattern.md) | RAG chat routes each question (lookup, aggregate, out of scope) before retrieval | RAG chat, Open WebUI pipe | Accepted |

## 0070-0079: dashboard, chat and n8n orchestration

| ADR | Title | Component | Status |
|---|---|---|---|
| [0071](0071-streamlit-for-the-dashboard.md) | Build the dashboard in Streamlit with Plotly, as a native multipage app | dashboard | Accepted |
| [0072](0072-demo-snapshot-for-public-dashboard.md) | Serve the public dashboard from a redacted parquet snapshot, not a live database | dashboard | Accepted; refined by ADR-0089 (snapshot is now the fallback) |
| [0073](0073-review-ui-inside-the-dashboard.md) | Put the human review form inside the dashboard, writing through vsia.review.decide | dashboard, review | Accepted |
| [0074](0074-dashboard-caching-policy.md) | Cache narrow read queries for five minutes and aggregate in pandas | dashboard | Accepted |
| [0075](0075-n8n-workflows-call-the-api-native-agent-is-a-variant.md) | Keep n8n workflows as thin API clients; ship the n8n-native agent as a comparison variant | n8n orchestration | Accepted |
| [0076](0076-open-webui-pipe-non-streaming-through-n8n.md) | Open WebUI pipe calls the n8n chat webhook and waits for one JSON answer | chat | Accepted |
| [0077](0077-header-auth-for-webhooks-and-api-tokens-in-credentials.md) | Protect n8n webhooks with header auth; keep the API token in an n8n credential | n8n orchestration | Accepted |
| [0078](0078-export-workflows-to-git-and-validate-statically.md) | Version n8n workflows as exported JSON and validate them statically | n8n orchestration | Accepted |

## 0080-0089: infrastructure and deployment

| ADR | Title | Component | Status |
|---|---|---|---|
| [0080](0080-docker-compose-on-one-a1-vm.md) | Run the cloud stack with Docker Compose on one Always Free A1 VM | infra | Accepted |
| [0081](0081-mlflow-sqlite-backend-on-shared-volume.md) | Use a SQLite MLflow backend on a volume shared with the API container | infra | Accepted |
| [0082](0082-tls-with-caddy-and-sslip-host-names.md) | Terminate TLS with Caddy, using sslip.io host names when there is no domain | infra | Accepted |
| [0083](0083-network-exposure-only-reverse-proxy-public.md) | Expose only the reverse proxy; keep Postgres on an internal network and MLflow behind SSH | infra | Accepted |
| [0084](0084-terraform-state-local.md) | Keep Terraform state local and gitignored | infra | Accepted |
| [0085](0085-cloud-init-bootstrap-secrets-over-ssh.md) | Bootstrap the VM with cloud-init; deliver secrets over SSH with a deploy script | infra | Accepted |
| [0086](0086-one-postgres-instance-per-service-databases.md) | Share one Postgres 16 instance with a database and role per service | infra | Accepted |
| [0087](0087-pinecone-index-managed-by-terraform.md) | Create the Pinecone index with Terraform | infra | Accepted |

## 0088-0099: shareable hosted demo

| ADR | Title | Component | Status |
|---|---|---|---|
| [0088](0088-free-tier-llm-for-the-hosted-demo.md) | Use free-tier Gemini for the hosted demo, with Groq as backup, visitor keys and an offline mode | LLM gateway, hosted demo | Accepted |
| [0089](0089-hosted-interactive-demo-on-streamlit-community-cloud.md) | Host an interactive demo on Streamlit Community Cloud that runs the agent in-process | dashboard, hosted demo | Accepted |
| [0090](0090-in-process-onnx-embedder-for-the-hosted-demo.md) | Embed queries in-process with the same nomic model (ONNX), not a hosted embedding API | retrieval | Accepted |
| [0091](0091-demo-data-bundle-as-release-asset.md) | Ship the demo data as a checksummed release asset, not in Git | hosted demo, data | Accepted |
| [0092](0092-quota-guard-and-visitor-key-handling.md) | Cap shared free-tier use per session and per day; keep visitor keys in the session only | hosted demo, security | Accepted |
| [0093](0093-backup-model-chain-for-the-shared-key.md) | Fall through a chain of free models on the shared key, failing fast between them | hosted demo, LLM gateway | Accepted |

## Notes

- ADR-0026 (guardrails range) and ADR-0077 (orchestration range) both decide header auth for the n8n
  webhooks and bearer-token auth for the API. They should be reconciled: one should reference or
  supersede the other.
- Code comments in `eval/build_gold.py`, `eval/splits.py` and `src/vsia/classifier.py` cite ADR-0040 to
  ADR-0046 by number; those numbers match the records above.
