# Threat model

- **Status:** Current as of 2026-10-19
- **System:** Vehicle Service Intelligence Agent (VSIA): defect intelligence for vehicle quality and
  service teams on public NHTSA complaint and recall data
- **Method:** STRIDE per trust boundary (Microsoft STRIDE; OWASP Threat Modeling Cheat Sheet), then the
  OWASP Top 10 for LLM Applications 2025, with a response per threat: mitigate, eliminate, transfer or
  accept. Process and section list follow `docs/research/01_documentation_process_research.md` (section
  (b) "Threat model" row and section (c) topic 10).
- **System model:** `docs/security/data-flow-diagram.md` (flow ids F0 to F54, gaps G1 to G12; the hosted
  demo is F42 to F54)
- **Related:** `docs/security/ai-risk-register.md` (risk ids R-xx), `docs/security/guardrails.md`,
  `docs/security/pii-handling.md`, ADR-0020 to ADR-0026, ADR-0088 to ADR-0092 (hosted demo)

The STRIDE-to-LLM mapping used here (for example prompt injection as Tampering and Elevation of
Privilege) is this project's own; neither OWASP nor Microsoft publishes an official mapping table.

## 1. Context that shapes the model

- All source data is public. NHTSA publishes complaint narratives and already masks some personal fields
  as `[XXX]` (669 of 10,303 loaded complaints contain that mask; see `pii-handling.md`). Confidentiality
  of the corpus is therefore a residual-PII concern, not a secrecy concern.
- The most consequential failure is an **integrity** failure: a safety-relevant complaint triaged as low
  severity and auto-routed, or linked to the wrong recall, which sends a service advisor to the wrong
  remedy.
- The Python triage path is a fixed workflow, not a free-running agent (ADR-0060). The model chooses no
  tools and triggers no side effects; it returns JSON that deterministic code validates and routes.
- The repository is open source, so system prompts are public by design.
- One operator runs the deployment. There is no multi-tenant data and no per-user authorisation.
- The hosted demo on Streamlit Community Cloud (ADR-0089) is public and anonymous by design. Visitors share
  one ephemeral SQLite database built from a redacted bundle, spend a shared free-tier model quota, and may
  paste their own API key. Its threats are in TB-H.

## 2. Assets

| ID | Asset | Security property that matters most | Where it lives |
|---|---|---|---|
| A1 | Complaint corpus (10,303 complaints, 8 makes) | Integrity; confidentiality of residual PII | Postgres `complaints` (unredacted `summary`) |
| A2 | Triage records (component, severity, recall links, route) | Integrity | Postgres `triage_records` |
| A3 | Review queue and review labels (feed the gold set and calibration) | Integrity, accountability | `review_queue`, `labels` |
| A4 | Recall corpus: 200 campaigns, 150 parsed documents, vector index | Integrity (poisoning) | `recalls`, `recall_documents`, `data/index`, Pinecone |
| A5 | Secrets: Anthropic, OpenAI, Pinecone and LlamaCloud keys; `VSIA_API_TOKEN`; `N8N_BEARER`; `N8N_ENCRYPTION_KEY`; database passwords; `WEBUI_SECRET_KEY` | Confidentiality | `infra/compose/.env`, n8n credentials, Open WebUI valves, Streamlit secrets |
| A6 | LLM and vector-store spend | Availability of budget | Provider accounts; measured in `llm_calls.cost_usd` |
| A7 | Prompts and prompt versions | Integrity (not confidentiality: public repo) | `src/vsia/prompts/`, `src/vsia/rag.py`, `src/vsia/documents.py`, workflow 05 |
| A8 | Chat histories and n8n execution data | Confidentiality | Open WebUI volume, n8n database |
| A9 | Evaluation ground truth (`components_raw`, `component_primary`) | Integrity: must never reach a triage prompt (label leakage, ADR-0005) | `complaints` |
| A10 | Service availability on one 12 GB VM | Availability | ADR-0080 |
| A11 | Audit trail (`llm_calls`, `ingestion_runs`, `confidence_signals`) | Integrity, non-repudiation | Postgres |
| A12 | Hosted demo secrets: the owner's free `GEMINI_API_KEY` and optional `GROQ_API_KEY`; bundle URL and checksum | Confidentiality (keys), integrity (checksum) | Streamlit secrets |
| A13 | Visitor-supplied API keys (Gemini, Groq, OpenAI, Anthropic) | Confidentiality | That browser session's state only |
| A14 | Shared free-tier quota on the owner's key (Gemini 1,000 requests per day as listed in ADR-0088; app cap 400 per ADR-0092) | Availability of the demo | Provider project; counted in the demo's `llm_calls` |
| A15 | Demo data bundle (redacted database, index, classifier, calibrators, routing files) | Integrity | GitHub release asset; container `data/` |

## 3. Trust boundaries

| ID | Boundary | Flows (DFD) |
|---|---|---|
| TB-A | Internet to public edge (Caddy) and through to exposed services | F15 to F20 |
| TB-B | Between application containers on the VM (Docker `frontend` and `backend` networks) | F18 to F24, F27 |
| TB-C | Application to LLM providers (Anthropic, OpenAI, Ollama) | F9, F25, F36 to F40 |
| TB-D | Application to public data sources and parsing services (NHTSA API, NHTSA PDF host, LlamaCloud) | F1, F3, F4, F7, F8, F26 |
| TB-E | Application to vector stores (local index, Pinecone) and embedding model | F12 to F14, F32 to F35 |
| TB-F | Application to persistent stores (Postgres, n8n DB, Open WebUI data, files) | F2, F5, F10, F22, F24, F27, F31, F41 |
| TB-G | Logical boundary inside the model context: untrusted data versus instructions | F9, F36, F37, F25 |
| TB-H | Hosted demo: anonymous visitor to the Streamlit app, the app to free-tier providers, and the release asset to the container | F42 to F54 |

## 4. STRIDE per trust boundary

Response key: **M** mitigate, **E** eliminate, **T** transfer, **A** accept. "Action" marks a residual
that is tracked in the risk register for a future code or configuration change.

### TB-A: Internet to public edge

| ID | STRIDE | Threat | Controls in place (file or function) | Response | Residual risk |
|---|---|---|---|---|---|
| A-S1 | Spoofing | Unauthenticated caller invokes the API or n8n webhooks to triage, chat or write review labels | `vsia.api.auth` bearer check on every route except `/health` (`src/vsia/api.py` lines 17 to 21); n8n Webhook header auth on `vsia-chat`, `vsia-review`, `vsia-triage-native` (ADR-0077); Open WebUI login; compose refuses to start without `VSIA_API_TOKEN` (`docker-compose.yml` line 135) | M | Low. Tokens are static and shared by all callers (ADR-0077 trade-off) |
| A-S2 | Spoofing | First visitor registers the Open WebUI admin account before the operator does | Caddyfile comment documents that the first account becomes admin | A, action | Medium during first deploy window; operator must create the admin account immediately |
| A-T1 | Tampering | Interception or modification in transit | Caddy automatic TLS with Let's Encrypt (ADR-0082) | M | Low |
| A-R1 | Repudiation | A reviewer denies a decision; decisions cannot be tied to a person | `labels.reviewer` stored; `review_queue.resolved_at` stored | A, action | Medium. `ReviewDecision.reviewer` is free text supplied by the caller (`src/vsia/schemas.py` line 131) and the bearer is shared, so the identity is asserted, not authenticated |
| A-I1 | Information disclosure | `/health` reveals provider, model, vector store and threshold without auth | None | A | Low; no secrets or records exposed (`src/vsia/api.py` lines 40 to 45) |
| A-I2 | Information disclosure | Timing side channel on token comparison | None; plain `!=` comparison (`src/vsia/api.py` line 20) | A, action | Low; use `hmac.compare_digest` |
| A-D1 | Denial of service and cost | Token holder or leaked token floods `/chat` (two LLM calls each) or `/triage/pending` with a large `limit` | Auth; `mem_limit` per container; output token caps; n8n workflow 01 sends `limit: 200` | M, action | Medium. No rate limit in Caddy or the API; `BatchRequest.limit`, `/search` `top_k` and `ChatRequest.question` length are unbounded (`src/vsia/api.py` lines 30 to 37, 95) |
| A-E1 | Elevation of privilege | API runs without auth when `VSIA_API_TOKEN` is unset | Compose makes the variable mandatory on the VM | A (laptop only) | Low on the VM; the API fails open by design on the laptop (`src/vsia/api.py` line 18 docstring) |

### TB-B: Between application containers

| ID | STRIDE | Threat | Controls in place | Response | Residual risk |
|---|---|---|---|---|---|
| B-S1 | Spoofing | A compromised container calls the API as n8n | API bearer token still required; Postgres only on the internal `backend` network (ADR-0083) | M | Low |
| B-T1 | Tampering | A workflow editor changes routing (for example sends everything to `auto`) | n8n owner account; workflows exported to Git and checked by `scripts/validate_n8n.py` (ADR-0078); routing logic lives in Python, not n8n (ADR-0001) | M | Low for workflows 01 to 04 (thin HTTP clients); medium for workflow 05, whose routing is in a Code node |
| B-I1 | Information disclosure | Workflow expressions read container secrets through `$env` | ADR-0077 keeps `VSIA_API_TOKEN` in an encrypted credential, not `$env` | A, action | Medium. `N8N_BLOCK_ENV_ACCESS_IN_NODE: "false"` (`docker-compose.yml` line 72) leaves `N8N_ENCRYPTION_KEY` (line 63) and `DB_POSTGRESDB_PASSWORD` (line 61) readable from any expression by anyone who can edit workflows |
| B-I2 | Information disclosure | MLflow has no authentication and is reachable from every container on `frontend` | MLflow holds no complaint text; not routed by Caddy; host port bound to `127.0.0.1` | A | Low |
| B-E1 | Elevation of privilege | Workflow 05's Postgres credential writes to `triage_records` directly as the `vsia` database owner, bypassing API validation | Workflow 05 is inactive by default (n8n README import step 5); parameterised query | A, action | Medium if activated. A least-privilege role limited to `INSERT` on `triage_records` would remove it |

### TB-C: Application to LLM providers

| ID | STRIDE | Threat | Controls in place | Response | Residual risk |
|---|---|---|---|---|---|
| C-S1 | Spoofing | Requests go to a spoofed provider endpoint | Fixed HTTPS URLs for Anthropic and OpenAI (`src/vsia/llm.py` lines 102 and 119) with certificate validation | M | Low. `OLLAMA_BASE_URL` is plain HTTP without auth; acceptable on localhost, not over a network |
| C-T1 | Tampering | Reply is malformed or adversarial (wrong types, invented campaign numbers, off-taxonomy labels) | `complete_json` Pydantic validation plus one repair retry (ADR-0007); taxonomy normalisation; `validate_citations`; component-overlap rule; severity rule (`src/vsia/agent.py` lines 127 to 152) | M | Low for structure; semantic errors remain and are measured in docs/evaluation/ (pending) |
| C-R1 | Repudiation | Cannot show which model and prompt produced a record | `llm_calls` row per call (provider, model, purpose, tokens, cost, latency, ok, prompt_version, ref_id); `triage_records.provider`, `model`, `prompt_version`, `schema_version`, `run_id` | M | Low |
| C-I1 | Information disclosure | Complaint PII sent to a third-party provider | `redact()` before every triage and extraction call (ADR-0021); providers' data handling is governed by their terms | M, T | Medium for chat: the RAG question is not redacted (gap G1, `src/vsia/rag.py` lines 54 and 109) |
| C-I2 | Information disclosure | Prompt or reply text written to logs | Gateway logs metadata only (`test_llm_calls_never_store_prompt_text`); span attributes scrubbed (`vsia.observability._scrub`) | M | Low. `llm_calls.error` can hold `input_value=` excerpts of model output (gap G6, `src/vsia/llm.py` line 170) |
| C-D1 | Denial of service | Provider outage, 429 or 5xx | Tenacity retry, 3 attempts, exponential backoff (`src/vsia/llm.py` lines 74 to 81); on failure the agent falls back to the TF-IDF heuristic and forces review (`src/vsia/agent.py` lines 121 to 125); runbook `docs/operations/runbooks/llm-provider-outage.md` | M | Low |
| C-E1 | Elevation of privilege | Model output causes an action | Fixed workflow, no model-selected tools in Python (ADR-0060); output is data only | E | None in the Python path |

### TB-D: Application to public data sources and parsing services

| ID | STRIDE | Threat | Controls in place | Response | Residual risk |
|---|---|---|---|---|---|
| D-S1 | Spoofing | Man in the middle on `api.nhtsa.gov` or `static.nhtsa.gov` | HTTPS with certificate validation (`httpx` default); SHA-256 per PDF in `data/docs/manifest.json` | M | Low |
| D-T1 | Tampering | Indirect prompt injection in a complaint narrative | `wrap_untrusted` (ADR-0024); `detect_injection` forces review (ADR-0023); `injection_suspected` field forces review; severity rule from structured flags (ADR-0062) | M | Medium. Paraphrased and non-English injections score 0 (see guardrails.md section 3.2) |
| D-T2 | Tampering | Indirect prompt injection in a recall PDF | `wrap_untrusted(..., tag="document")` in `extract_llm`; rules-first extraction so most documents never reach an LLM (ADR-0032); campaign number and source URL overwritten from known facts (`src/vsia/documents.py` lines 212 to 214) | M | Low |
| D-T3 | Tampering | Coordinated fake complaints skew the weekly forecast or spike alerts | Alerts go to a human, not an automated action; NHTSA's own intake process | T, A | Medium; out of the project's control |
| D-T4 | Tampering | Malicious PDF exploits the parser | Size caps (1 MB owner letters, 3 MB overall) in `scripts/fetch_recall_docs.py`; `pypdf` text extraction; `tesseract` run as a subprocess with a 120 s timeout | M | Low; depends on parser patches (LLM03) |
| D-R1 | Repudiation | Cannot show what was ingested and when | `ingestion_runs` row per run (fetched, inserted, duplicate, filtered, error); PDF manifest with hashes | M | Low |
| D-I1 | Information disclosure | Raw PDFs uploaded to LlamaCloud before redaction | Optional path; documents are public NHTSA files | A | Low (gap G7) |
| D-D1 | Denial of service | NHTSA throttling or outage | Retries on 429 and 5xx (`src/vsia/nhtsa.py` lines 17 to 31); throttling sleeps in `vsia/ingest.py`; runbook `ingestion-failed.md` | M | Low |

### TB-E: Application to vector stores and embedding model

| ID | STRIDE | Threat | Controls in place | Response | Residual risk |
|---|---|---|---|---|---|
| E-S1 | Spoofing | Stolen Pinecone key used to read or write the index | Key only in `.env` and the container environment; index is rebuildable from Postgres | M | Low |
| E-T1 | Tampering | Poisoned records inserted into the index steer recall candidates | Index rebuilt from the database by `scripts/build_index.py`; citation grounding limits cited campaigns to the candidate set; component-overlap rule; recall summaries in candidates come from the `recalls` table via `recall_lookup` | M | Low to medium: a poisoned index can still add a candidate to the allowed set |
| E-I1 | Information disclosure | PII embedded or stored as record text in a third-party index | Complaint text redacted before indexing (`scripts/build_index.py` line 92); documents redacted before storage; NHTSA labels excluded from the complaint index (ADR-0005) | M | Low |
| E-I2 | Information disclosure | Embedding inversion | Text is stored next to the vectors anyway and is redacted | A | Low |
| E-D1 | Denial of service | Pinecone free-tier limits or outage | `VSIA_VECTOR_STORE=local` fallback (ADR-0030) | M | Low |

### TB-F: Application to persistent stores

| ID | STRIDE | Threat | Controls in place | Response | Residual risk |
|---|---|---|---|---|---|
| F-S1 | Spoofing | Direct database login from outside | Postgres on internal network only, per-service roles and databases, `REVOKE ALL ... FROM PUBLIC` (`infra/compose/postgres-init.sql`, ADR-0086) | M | Low |
| F-T1 | Tampering | SQL injection through complaint text or API input | SQLAlchemy Core with bound parameters throughout; n8n Postgres node uses `queryReplacement` parameters | E | Low |
| F-R1 | Repudiation | Overwritten history | Complaints are insert-only (duplicates skipped, never overwritten, `vsia/ingest.py`); each triage run inserts a new record with `run_id` | M | Low |
| F-I1 | Information disclosure | Unredacted text at rest | `complaints.summary` is stored unredacted by design (public source); recall documents redacted before storage (ADR-0021) | A | Medium for chat history: Open WebUI data and n8n execution data hold unredacted questions and full message history for 336 hours (gap G4) |
| F-I2 | Information disclosure | Unredacted summary persisted in model output | None | A, action | Medium. The heuristic fallback copies 160 unredacted characters into `extracted.symptom` (gap G2, `src/vsia/agent.py` line 88); the dashboard redacts it on read (`app/data.py` `redact_obj`) but the database and the `/triage` response do not |
| F-D1 | Denial of service | Disk or memory exhaustion on the VM | `mem_limit` per container; Docker log rotation (10 MB x 3); n8n execution pruning; runbook `vm-out-of-capacity.md` | M | Low |

### TB-G: Model context (data versus instructions)

| ID | STRIDE | Threat | Controls in place | Response | Residual risk |
|---|---|---|---|---|---|
| G-S1 | Spoofing | Complaint impersonates a system or assistant turn | `wrap_untrusted` strips chat-template tokens (`<\|im_start\|>`, `[INST]`, `<<SYS>>`) and neutralises spoofed `</complaint>` tags in raw, HTML-entity and full-width forms (`test_wrap_untrusted_neutralises_tag_spoofing`) | M | Low for the wrapped block; candidate recalls and RAG context are not neutralised (gap G3) |
| G-T1 | Tampering | Injection steers severity, component or routing | Detector score at or above 0.5 forces review; model-reported `injection_suspected` forces review; severity rule overrides to S1 on crash, fire, injury or death flags; calibrated confidence uses an independent TF-IDF signal (ADR-0061) | M | Medium: an undetected injection that lowers severity on a complaint without structured flags can still auto-route if confidence is high |
| G-R1 | Repudiation | Cannot reconstruct why a record was routed | `confidence_signals` stores `injection_score`, `pii_redactions`, `citations_dropped`, `severity_rule_override`, `llm_severity`, `review_reasons` | M | Low |
| G-I1 | Information disclosure | System prompt exfiltration | Prompts are public; no secrets in any prompt; keys travel only in HTTP headers; `prompt_exfiltration` detector rule | A | None of consequence |
| G-D1 | Denial of service | Long input inflates tokens | NHTSA narratives are bounded (longest loaded summary: 2,830 characters); search query truncated to 2,000 characters; document LLM input truncated to 12,000 characters; output caps 200 to 800 tokens | M | Low for NHTSA data; caller-supplied complaints and chat questions are not length-capped |
| G-E1 | Elevation of privilege | Injection makes the model call tools or act | No tools in the Python path; workflow 05 tools are read-only `GET` calls with `maxIterations: 5` | E (Python), M (n8n) | Low |

### TB-H: Hosted demo (Streamlit Community Cloud)

The triage and chat guardrails in TB-C, TB-E and TB-G apply unchanged inside the hosted app; this table
covers only what the hosted deployment adds.

| ID | STRIDE | Threat | Controls in place | Response | Residual risk |
|---|---|---|---|---|---|
| H-S1 | Spoofing | Anyone uses the demo, and any visitor can type any reviewer name on the Human review page | None by design: public demo, public data, ephemeral database (ADR-0089) | A | Low. The hosted database is separate from the development database and is discarded on restart, so visitor decisions never reach the gold set or calibration |
| H-T1 | Tampering | A replaced release asset or a man in the middle serves a malicious bundle: poisoned database or index, or a joblib classifier or calibrator that runs code when loaded | HTTPS download; sha256 compared with `VSIA_BUNDLE_SHA256`; extraction limited to regular files and directories under `data/`, rejecting absolute paths and `..` (`vsia.bundle._safe_members`); tests `test_bundle_rejects_paths_outside_data`, `test_bundle_build_redacts_and_ensure_installs` | M, action | Low when the checksum secret is set, as the runbook requires. Verification is skipped when `VSIA_BUNDLE_SHA256` is unset (gap G10) |
| H-T2 | Tampering | Visitor free text (written complaint or chat question) carries a prompt injection, or visitors fill the shared database | Same guardrails as TB-G: redaction, `detect_injection` forcing review, `wrap_untrusted`, schema validation, grounding; inputs capped at 2,000 and 500 characters; written complaints run with `persist=False`, so they write no triage or review row; chat history stays in session state; picked complaints persist triage records derived from public, redacted text | M | Low. Visitor review decisions do persist in the shared database until restart (gap G11) |
| H-R1 | Repudiation | Visitor actions cannot be attributed to a person | Triage records tagged `playground-<session>`; `llm_calls` metadata | A | Low; anonymity is intended for a public demo |
| H-I1 | Information disclosure | A visitor's own API key leaks through logs, the database, error text or another session | Password field; kept in that browser session's state; passed per request through `vsia.llm.use_keys()`, a context variable reset when the block ends; keys travel only in request headers; never written to the database, logs or `llm_calls`; gateway error strings carry no request headers (ADR-0092); test `test_use_keys_overrides_environment_and_resets` | M | Low. The visitor must still trust the deployed code and Community Cloud; the key field tells them it is never stored or logged |
| H-I2 | Information disclosure | The free-tier provider may use submitted content to improve its products (Google's free-tier terms, ADR-0088) | Only public NHTSA text after PII redaction is sent: the bundle database is redacted at build (RP9), triage redacts before the call (RP1), chat redacts the question (RP10); the "Write your own" tab tells visitors not to enter personal information | T, A | Low to medium: regex redaction misses some PII (R-02), and a visitor can ignore the warning |
| H-I3 | Information disclosure | The owner's shared key leaks | Key only in Streamlit secrets; never shown in the UI; the runbook requires a project with no billing account, so a leaked key cannot incur charges; rotation steps in the runbook | M | Low |
| H-D1 | Denial of service (denial of wallet on a free tier) | One visitor or a script uses up the shared daily quota, so later visitors get errors | Per-session cap of 15 AI calls and per-day cap of 400 calls per provider counted from `llm_calls` since midnight Pacific (ADR-0092); Groq backup on 429; visitor's own key; offline classifier; the agent's failure mode routes to review with the reason shown | M, action | Medium. New browser sessions bypass the session cap until the daily cap; the daily count lives in the ephemeral database and restarts at 0 after an app restart; the Groq retry is not counted (gap G12). No money is at risk on a project without billing |
| H-D2 | Denial of service | The app hits the Community Cloud memory ceiling, sleeps, or cannot download the bundle | Runbook incidents table; reboot from Manage app; sleep page wakes the app | A | Medium. Memory use on Community Cloud is not yet measured; a failed bundle download or checksum mismatch stops the page with an error instead of falling back to the snapshot |
| H-E1 | Elevation of privilege | A visitor gains code execution or file access in the container | No tools, shell or file upload; model output is data only; safe tar extraction (H-T1) | M | Low |

## 5. OWASP Top 10 for LLM Applications 2025

| OWASP id | How it applies to VSIA | Controls in this code | Residual risk | Response |
|---|---|---|---|---|
| LLM01 Prompt Injection | Every complaint narrative and recall document is untrusted text that enters a prompt (indirect injection); chat questions are direct input | `guardrails.wrap_untrusted` (spotlighting, tag and special-token neutralisation); `guardrails.detect_injection` (15 weighted rules, noisy-OR, flag at 0.5) forcing review in `agent.triage`; security rules at the top of `prompts/triage_v1.md`; `TriageOutput.injection_suspected` forces review; deterministic validation of every output; no tools to abuse. ADR-0023, ADR-0024 | Medium. Heuristic detection misses paraphrase and non-English attacks; candidate recalls and RAG context are not neutralised (G3); OWASP itself states fool-proof prevention may not exist | M |
| LLM02 Sensitive Information Disclosure | Narratives can contain names, phones, emails, addresses, VINs | `guardrails.redact` before LLM, embedding, document storage, search queries, dashboard and snapshot export; metadata-only `llm_calls`; `observability._scrub`. ADR-0020, ADR-0021, ADR-0022 | Medium: regex misses lowercase names, SSNs, non-US phones (see pii-handling.md section 7); RAG question not redacted (G1); heuristic symptom unredacted (G2); chat history retained (G4) | M, A |
| LLM03 Supply Chain | Hosted models (Anthropic `claude-haiku-5-5`, OpenAI `gpt-6-luna`; Gemini `gemini-2.5-flash-lite` and Groq `openai/gpt-oss-20b` in the hosted demo), the fastembed ONNX model and the demo data bundle (H-T1), local `qwen2.5:3b` and `nomic-embed-text` via Ollama, Pinecone `llama-text-embed-v2`, LlamaParse, Python packages, container images | Model ids pinned in `config/settings.yaml`; images pinned for n8n 2.43.7, MLflow v3.17.1, Open WebUI v0.12.3; no fine-tuned or third-party adapter weights; offline-first default path (ADR-0002) | Medium. Python dependencies use `>=` lower bounds with no lock file in the repo (`pyproject.toml`); `postgres:16-alpine` and `caddy:2-alpine` are floating tags; the `httpRequestTool` node type in workflow 05 is inferred, not verified (n8n README) | M, A |
| LLM04 Data and Model Poisoning | No LLM is trained or fine-tuned. Poisonable inputs: the complaint corpus (forecast and retrieval), the vector index, the TF-IDF classifier trained on NHTSA labels, the confidence calibrator, and review labels that feed the gold set | Index rebuilt from the database; review labels require the bearer token or the n8n webhook bearer; calibrator fitted on a held-out calibration split (`vsia.confidence.fit`); evaluation runs isolated from the review queue (ADR-0064) | Low to medium: a token holder can write arbitrary review labels; reviewer identity is unauthenticated | M, A |
| LLM05 Improper Output Handling | Model output is persisted, returned by the API, rendered in Open WebUI and in the dashboard | Pydantic schema validation with one repair retry; taxonomy normalisation; citation grounding; parameterised SQL; dashboard escapes model text with `ui.escape_md` (`app/views/triage.py`, `app/views/review.py`); campaign numbers validated by pattern `^\d{2}[VEITC]\d{6}$` | Low to medium. The RAG `answer` text is returned and rendered as Markdown by `openwebui/vsia_pipe.py` `render_answer` without sanitisation; inline bracketed citations inside `answer` are not filtered, only the `citations` list is | M |
| LLM06 Excessive Agency | An agent with write tools could alter records or call external systems | Fixed workflow (ADR-0060); both Python tools are read-only; `recall_lookup(live=False)` reads the local table by default; routing and persistence are deterministic code; workflow 05 tools are `GET` only, `maxIterations: 5`, and the database write is a fixed node | Low. Workflow 05 can call the public NHTSA API with model-chosen parameters (read-only) | E (Python), M (n8n) |
| LLM07 System Prompt Leakage | The prompts are in a public repository | No credentials, keys, internal URLs or authorisation logic in any prompt; authorisation is enforced in `vsia.api.auth` and n8n, never by the prompt | None of consequence | A |
| LLM08 Vector and Embedding Weaknesses | Pinecone or local index holds complaint and recall text | Single-tenant public data (no cross-tenant leakage possible); redaction before embedding; NHTSA labels excluded from the complaint index; separate indexes per embedding model (`vsia/retrieval.py` docstring); vehicle filters via `vehicle_keys` | Low: index poisoning (E-T1) | M, A |
| LLM09 Misinformation | Wrong component, severity or recall link; invented counts or IDs in chat | `validate_citations` against the retrieved set (ADR-0025); component-overlap rule (ADR-0063); severity business rule (ADR-0062); calibrated confidence and review routing (ADR-0061); RAG out-of-scope refusal and SQL-computed counts for aggregate questions (ADR-0065); answer prompt forbids invented numbers | Medium until accuracy is measured: measured in docs/evaluation/ (pending) | M |
| LLM10 Unbounded Consumption | Every `/chat` costs two LLM calls; every triage one call plus at most one repair retry | `max_output_tokens: 700` (triage), 200 (plan), 500 (answer), 800 (extraction); one repair retry; 3 transport attempts; cost per call in `llm_calls.cost_usd`; runbook `cost-spike.md`; Ollama `num_ctx: 4096`; hosted demo session and daily caps on the shared key (ADR-0092, H-D1) | Medium: no request rate limit on the API; uncapped `limit`, `top_k` and question length on the API; caller can select the provider per request (`TriageRequest.provider`, `ChatRequest.provider`, forwarded by workflow 04) | M, action |

## 6. Summary of responses

| Response | Threat ids |
|---|---|
| Eliminate | C-E1, F-T1, G-E1 (Python path), LLM06 (Python path) |
| Mitigate (in place) | A-S1, A-T1, B-S1, B-T1, C-S1, C-T1, C-R1, C-D1, D-S1, D-T1, D-T2, D-T4, D-R1, D-D1, E-S1, E-T1, E-I1, E-D1, F-S1, F-R1, F-D1, G-S1, G-T1, G-R1, G-D1, H-T2, H-I1, H-I3, H-E1 |
| Transfer | C-I1 (provider data terms), D-T3 (NHTSA intake), H-I2 (free-tier provider terms) |
| Accept | A-I1, A-E1 (laptop), B-I2, D-I1, E-I2, G-I1, LLM07, H-S1, H-R1, H-D2 |
| Accept now, action tracked | A-S2, A-R1, A-I2, A-D1, B-I1, B-E1, F-I1, F-I2, H-T1, H-D1, gaps G1 to G8 and G10 to G12 |

Each "action tracked" item has a row in `docs/security/ai-risk-register.md` with an owner role and status.

## 7. Assumptions and out of scope

- The OCI tenancy, VM operating system hardening and SSH (`admin_cidr` only, ADR-0083 and ADR-0085) are
  covered by the infrastructure ADRs, not re-analysed here.
- Provider-side security (Anthropic, OpenAI, Google Gemini, Groq, Pinecone, LlamaCloud) is transferred to
  their terms.
- Streamlit Community Cloud runs the interactive hosted demo (ADR-0089, TB-H) on a bundle redacted at build
  (`vsia.bundle.build`, ADR-0091). The demo snapshot, redacted at export (`scripts/export_demo_snapshot.py`,
  ADR-0072), is the fallback. Community Cloud platform security is transferred to Streamlit.
- No workflow in `workflows/n8n/` has been executed in a running n8n instance yet (n8n README, ADR-0008);
  n8n findings are from the exported JSON.

## 8. Maintenance

Update this file when a data flow, trust boundary, tool, prompt version or provider changes, and at least
once per release. Re-run the measurements in `pii-handling.md` and the guardrail tests after any change to
`src/vsia/guardrails.py`.
