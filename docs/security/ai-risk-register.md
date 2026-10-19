# AI risk register

- **Status:** Current as of 2026-10-19
- **Framework:** NIST AI Risk Management Framework 1.0 (January 2023): functions Govern, Map, Measure,
  Manage. Risk categories from NIST AI 600-1, Generative AI Profile (July 2024). NIST states AI RMF 1.0
  is under revision, so the version numbers are cited explicitly.
- **Inputs:** `docs/security/threat-model.md` (threat ids such as C-I1), `docs/security/data-flow-diagram.md`
  (gaps G1 to G9), `docs/security/pii-handling.md`, `docs/security/guardrails.md`
- **Format guidance:** `docs/research/01_documentation_process_research.md`, section (b), "AI risk
  register" row (risk, NIST function, owner, control, status)

## How to read this register

**NIST function** is the function under which the main response sits:

| Function | Meaning in this project |
|---|---|
| Govern | Policies, ownership, decision records, secrets handling, change control |
| Map | Knowing the context: data sources, users, dependencies, where untrusted data enters |
| Measure | Tests, corpus measurements, evaluation metrics |
| Manage | Controls that act at run time: redaction, validation, routing, retries, budgets |

**Likelihood** and **Impact** use three levels:

| Level | Likelihood | Impact |
|---|---|---|
| Low | Not expected in normal operation, or measured as rare | Cosmetic, or caught by a later control |
| Medium | Plausible in normal operation | Wrong record that review or evaluation would catch; limited PII exposure |
| High | Expected without the control | Safety-relevant complaint mis-triaged and auto-routed; credential compromise; uncontrolled spend |

Likelihood is the rating **with** the listed control in place. Where a corpus measurement exists it is
quoted in the evidence column.

**Owner roles:** AI workflow engineer (code, prompts, guardrails); Operator (deployment, secrets,
n8n, VM); Evaluation owner (gold set, metrics); Review lead (human review queue). In this portfolio
project one person holds all four roles; the roles are listed so the register transfers to a team.

**Status values:** Implemented; Partial; Open (action needed); Accepted (residual risk accepted, with
reason); Pending measurement.

## Register

| ID | Risk | NIST function | AI 600-1 category | Likelihood | Impact | Owner role | Control | Status | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| R-01 | Complaint PII reaches an LLM provider during triage or document extraction | Manage | Data Privacy | Low | Medium | AI workflow engineer | `guardrails.redact()` before every triage and extraction call (`agent.py` line 101, `documents.py` line 255); ADR-0020, ADR-0021 | Implemented | `test_redacts_each_pii_type` (22 cases), `test_counts_cover_multiple_types_in_one_text`, `test_redaction_is_idempotent`; corpus measurement in `pii-handling.md` section 6 |
| R-02 | Regex redaction misses PII the rules do not cover (lowercase names, names without a cue, SSNs, non-US phone numbers, lowercase VINs) | Measure | Data Privacy | Low | Medium | AI workflow engineer | NHTSA masks personal fields upstream (`[XXX]` in 669 complaints); 22 positive and 26 false-positive guard tests; known misses documented | Accepted | `pii-handling.md` section 7 (probe results); ADR-0020 "Revisit when" |
| R-03 | RAG chat question is sent to the LLM provider without redaction | Manage | Data Privacy | Medium | Medium | AI workflow engineer | Question is wrapped (`wrap_untrusted`) but not redacted (`rag.py` lines 54, 109) | Open | Gap G1; no test |
| R-04 | Heuristic fallback writes 160 unredacted characters of the narrative into `extracted.symptom`, persisted and returned by `/triage` | Manage | Data Privacy | Medium (every LLM failure and every heuristic run) | Low (public text, low PII prevalence) | AI workflow engineer | Dashboard redacts on read (`app/data.py` `redact_obj`); none at write time (`agent.py` line 88) | Open | Gap G2; no test |
| R-05 | Chat questions and full message history retained unredacted in Open WebUI and n8n execution data (336 hours) | Govern | Data Privacy | Medium | Low | Operator | n8n execution pruning (`EXECUTIONS_DATA_MAX_AGE: 336`); both stores on the internal network | Accepted | Gap G4; `docker-compose.yml` lines 77 and 78; `vsia_pipe.py` line 98 |
| R-06 | `llm_calls.error` and `confidence_signals.llm_error` hold `input_value=` excerpts of model output, contrary to the metadata-only logging rule | Manage | Data Privacy | Medium (on every validation failure) | Low (model output derives from redacted text) | AI workflow engineer | Error truncated to 400 and 300 characters (`llm.py` line 170, `agent.py` line 124) | Open | Gap G6 |
| R-07 | Indirect prompt injection in a complaint narrative changes severity, component or routing | Manage | Information Integrity; Information Security | Low (corpus: 0 of 10,303 complaints flagged) | High | AI workflow engineer | `wrap_untrusted`; `detect_injection` forces review; `injection_suspected` forces review; severity rule; no tools; ADR-0023, ADR-0024 | Implemented | `test_injection_examples_are_flagged` (10 attacks), `test_benign_complaints_are_not_flagged` (10 benign), `test_wrap_untrusted_neutralises_tag_spoofing` (8 spoofs), `test_wrap_untrusted_removes_chat_template_tokens` |
| R-08 | Injection detector false negatives (paraphrase, other languages, encodings beyond base64 length rule) | Measure | Information Security | Medium | Medium | AI workflow engineer | Defence in depth: wrapping, model self-report, output validation, calibrated confidence | Partial | Probe in `guardrails.md` section 3.2: a paraphrased English and a Spanish override both score 0.0; adversarial evaluation set: measured in docs/evaluation/ (pending) |
| R-09 | Retrieved recall chunks and RAG context are inserted into prompts without tag neutralisation, so a poisoned chunk can close `<candidate_recalls>` or `<context>` | Manage | Information Security | Low (sources are NHTSA documents) | Medium | AI workflow engineer | Citation grounding still restricts IDs to the retrieved set | Open | Gap G3; `agent.py` lines 67 to 73; `rag.py` lines 91, 99, 109 |
| R-10 | Model cites a recall campaign or complaint id that was not retrieved (confabulation) | Manage | Confabulation | Low | High | AI workflow engineer | `validate_citations` against the candidate or context set (ADR-0025); `RecallMatch.campaign_number` pattern | Implemented | `test_validate_citations_drops_ungrounded_ids`, `test_validate_citations_empty_inputs`; `signals.citations_dropped` per record |
| R-11 | Model links a real but unrelated recall (right vehicle, wrong part) | Measure | Confabulation | Medium | High | Evaluation owner | Component-overlap rule (`agent.py` lines 136 to 140; ADR-0063) | Pending measurement | No unit test of the overlap rule; match precision measured in docs/evaluation/ (pending) |
| R-12 | Safety-relevant complaint under-classified (S3 or S4) | Manage | Information Integrity; Human-AI Configuration | Medium | High | AI workflow engineer | Severity business rule: crash, fire, injury or death flags force S1 (`agent.py` lines 146 to 152; ADR-0062); `severity_rule_override` signal | Partial | No unit test of the rule; severity accuracy measured in docs/evaluation/ (pending). Narratives without structured flags rely on the model and on review routing |
| R-13 | Automation bias: auto-routed records are trusted without review | Govern | Human-AI Configuration | Medium | High | Review lead | Calibrated confidence threshold (ADR-0061); review reasons recorded; review queue and digest (workflow 02) | Partial | No calibrator fitted yet (`data/models/` absent), so `fallback_weights` is used; random audit sample of auto-routed records not implemented; routing quality measured in docs/evaluation/ (pending) |
| R-14 | Output does not match the schema | Manage | Confabulation | Low | Medium | AI workflow engineer | Provider structured output, Pydantic validation, one repair retry, then heuristic fallback and forced review (ADR-0007) | Implemented | `test_complete_json_repairs_invalid_json_on_second_attempt`, `test_complete_json_repairs_schema_violation`, `test_complete_json_both_invalid_raises_and_logs_failure` |
| R-15 | NHTSA component labels (evaluation ground truth) leak into a triage prompt or the complaint index | Govern | Information Integrity | Low | High | AI workflow engineer | `_user_message` sends only make, model, year, redacted narrative and candidates; `scripts/build_index.py` excludes labels; AGENTS.md rule 3; ADR-0005 | Implemented | Code review of `agent.py` lines 67 to 73 and `scripts/build_index.py`; no automated leakage test |
| R-16 | Unbounded consumption: request floods, oversized batches or questions, caller-chosen provider | Manage | Information Security (availability and cost) | Medium | Medium | Operator | Bearer auth; output token caps; one repair retry; cost per call logged; runbook `cost-spike.md` | Partial | `test_price_math`, `test_cost_latency_summary`, `test_cost_per_1000`; no rate limit; uncapped `limit`, `top_k`, question length (`api.py` lines 24 to 37, 95) |
| R-17 | n8n expressions can read `N8N_ENCRYPTION_KEY` and the n8n database password through `$env` | Govern | Information Security | Low (requires editor access) | High | Operator | n8n owner account; API token kept in an encrypted credential (ADR-0077) | Open | `docker-compose.yml` lines 61, 63, 72 |
| R-18 | Shared static tokens; reviewer identity is asserted, not authenticated | Govern | Human-AI Configuration; Information Security | Medium | Medium | Operator | Rotation procedure (ADR-0077, `cost-spike.md`); `labels.reviewer` stored | Accepted | `schemas.py` line 131; single operator deployment |
| R-19 | Supply chain: unpinned Python dependencies, floating `postgres` and `caddy` tags, model ids retired by providers | Govern | Value Chain and Component Integration | Medium | Medium | Operator | Pinned n8n, MLflow and Open WebUI images; model ids and prices dated in `config/settings.yaml`; offline-first default (ADR-0002) | Partial | `pyproject.toml` (lower bounds only, no lock file); `docker-compose.yml` lines 25 and 181 |
| R-20 | LLM provider outage or rate limiting stops triage | Manage | Value Chain and Component Integration | Medium | Low | Operator | Retries with backoff; heuristic fallback with forced review; provider switch by configuration (ADR-0002) | Implemented | `test_complete_json_provider_exception_is_logged_without_retry`; runbook `llm-provider-outage.md` |
| R-21 | Provider silently updates a model, changing behaviour | Measure | Value Chain and Component Integration | Medium | Medium | Evaluation owner | `provider`, `model`, `prompt_version` stored on every record and call | Pending measurement | Regression evaluation per release: measured in docs/evaluation/ (pending) |
| R-22 | n8n workflow 05 bypasses the Python guardrails (partial redaction, no injection score, no grounding against tool output, no severity rule, no review-queue row) | Govern | Information Integrity; Data Privacy | Low (inactive by default) | Medium | Operator | Demo variant only (ADR-0001, ADR-0075); records tagged `prompt_version = n8n-native-v1` and `run_id` `n8n-native-*` | Accepted | Gap G5; `workflows/n8n/README.md` "Known gaps" |
| R-23 | Poisoning of the vector index or of review labels skews retrieval, calibration or the gold set | Map | Information Integrity | Low | Medium | Evaluation owner | Index rebuilt from the database; label writes need a bearer; evaluation isolated from the review queue (ADR-0064) | Partial | `scripts/build_index.py`; `vsia/review.py` `decide` |
| R-24 | Coordinated or fake complaints create false spike alerts | Map | Information Integrity | Low | Medium | Review lead | Alerts go to a human; no automated action on a spike | Accepted | `/forecast/run` returns alerts only (`api.py` lines 115 to 131) |
| R-25 | Uneven accuracy across makes or components (8 makes with very different complaint volumes) | Measure | Harmful Bias and Homogenization | Medium | Medium | Evaluation owner | Per-slice metrics planned in the evaluation | Pending measurement | Measured in docs/evaluation/ (pending) |
| R-26 | Chat answer rendered as Markdown with unfiltered inline citations or links | Manage | Information Integrity | Low | Low | AI workflow engineer | `citations` list filtered by `validate_citations`; dashboard escapes model text (`ui.escape_md`) | Partial | `openwebui/vsia_pipe.py` `render_answer`; `test_answer_with_sources_and_events` |
| R-27 | VIN stored longer than the 11-character prefix if NHTSA ever returns a full VIN | Manage | Data Privacy | Low (loaded lengths 9 to 11) | Low | AI workflow engineer | None at ingest; ADR-0022 policy | Open | Gap G8; `nhtsa.py` line 86; `db.py` `vin_prefix String(17)` |
| R-28 | Raw recall PDFs sent to LlamaCloud before redaction | Map | Data Privacy | Low (optional path) | Low (public documents) | Operator | Default parser is local `pypdf` (ADR-0031) | Accepted | Gap G7 |
| R-29 | Decisions and controls undocumented or drift from code | Govern | Information Integrity | Medium | Medium | AI workflow engineer | ADRs (MADR template), this register, threat model, DFD, prompt specs with version ids | Partial | This document set; inconsistencies listed in `guardrails.md` section 9 |

## Measurements behind the register

| Measurement | Value | Command and date |
|---|---|---|
| Complaints scanned | 10,303 | `.venv/bin/python -c "from vsia.guardrails import measure_corpus; ..."`, 2026-10-19 (see `pii-handling.md` section 6) |
| Complaints with any detected PII | 75 (0.73%) | same |
| Complaints flagged by `detect_injection` | 0 | same |
| Weak injection rule hits below threshold | `visit_url` 3, `system_prompt_mention` 1, `you_are_now` 1 | same |
| Guardrail tests | 89 tests in `tests/test_guardrails.py`; 115 tests pass across `test_guardrails.py`, `test_llm_gateway.py`, `test_openwebui_pipe.py` | `.venv/bin/python -m pytest -q tests/test_guardrails.py tests/test_llm_gateway.py tests/test_openwebui_pipe.py`, 2026-10-19 |
| Component accuracy, severity accuracy, recall-match precision, routing quality | measured in docs/evaluation/ (pending) | n/a |

## Review cadence

Review this register when a prompt version, provider, model id, tool or guardrail changes, and at every
release. Close an "Open" row only with a linked commit and, where possible, a test name in the evidence
column.
