# Runtime sequences

These are C4 dynamic views: the runtime order of calls between containers and components for the six
main use cases. Static structure is in the [container view](c4-container.md) and the
[triage component view](c4-component-triage.md); data at rest is in the
[data dictionary](../data/data-dictionary.md). Each diagram names the real functions and endpoints in the
code so it can be checked against it.

1. [Daily ingestion via n8n](#1-daily-ingestion-via-n8n)
2. [Single complaint triage](#2-single-complaint-triage)
3. [Low-confidence routing to human review, and the decision becoming a label](#3-low-confidence-routing-to-human-review-and-the-decision-becoming-a-label)
4. [RAG chat through the Open WebUI pipe, n8n and the API](#4-rag-chat-through-the-open-webui-pipe-n8n-and-the-api)
5. [Weekly forecast and spike alert](#5-weekly-forecast-and-spike-alert)
6. [Recall document parsing and indexing](#6-recall-document-parsing-and-indexing)

Conventions: solid arrows are calls, dashed arrows are returns. "API" is the FastAPI service
(`src/vsia/api.py`); "DB" is SQLite on the laptop or Postgres on the VM (ADR-0003). n8n workflows have not
yet been executed in a running instance (ADR-0008, ADR-0078); the n8n parts below describe the exported
workflow JSON.

---

## 1. Daily ingestion via n8n

n8n workflow `01_daily_ingest_and_triage.json` (FR-1, FR-4; ADR-0001, ADR-0004, ADR-0075). The HTTP nodes
use 15-minute (ingest) and 30-minute (triage) timeouts, `retryOnFail` and an error output.

```mermaid
sequenceDiagram
  autonumber
  participant S as n8n Schedule 06:00
  participant N as n8n workflow 01
  participant A as VSIA API
  participant I as vsia.ingest
  participant H as NHTSA API
  participant D as DB
  participant W as Notify webhook

  S->>N: trigger (cron 0 6 * * *)
  N->>A: POST /ingest/daily (bearer)
  A->>I: ingest_complaints()
  I->>I: resolve_vehicles() from data/raw/scoped_vehicles.json cache
  I->>D: SELECT odi_number FROM complaints (seen set)
  loop each scoped vehicle (make, model, model year)
    I->>H: GET /complaints/complaintsByVehicle
    H-->>I: results (HTTP 400 means no match, returned as empty)
    I->>I: normalize_complaint, skip seen ODI, filter (no summary, exclude_models, filed before segment.filed_from)
    I->>I: component_primary = primary_component(components_raw)
    I->>D: INSERT complaints (batch)
  end
  I->>D: INSERT ingestion_runs (kind complaints_api, counts, ok, error, per_vehicle)
  A->>I: ingest_recalls()
  I->>D: SELECT DISTINCT make, model, model_year FROM complaints
  loop each vehicle string
    I->>H: GET /recalls/recallsByVehicle
    H-->>I: results
    I->>D: INSERT recalls (new campaign x vehicle keys only)
  end
  I->>D: INSERT ingestion_runs (kind recalls)
  A-->>N: 200 with complaints and recalls counts (ok flag in the body)
  alt complaints.ok and recalls.ok
    opt complaints.rows_inserted greater than 0
      N->>A: POST /triage/pending with limit 200
      A-->>N: run_id, triaged, auto, review
    end
    N->>W: summary (fetched, inserted, triaged, auto vs review), node disabled until URL set
  else ingest failed, HTTP error or timeout
    N->>W: failure message
    N->>N: Mark Execution Failed (throws, so the run shows as failed)
  end
```

Notes:
- The API reports a failed complaint loop with `ok: false` inside an HTTP 200 body; workflow 01 checks the
  flag explicitly. A fetch error for one vehicle is logged and skipped, so `ok` stays true; only an error
  outside the per-vehicle loop sets it false. The recall run always records `ok: true` (see
  [lineage](../data/lineage.md#known-lineage-gaps)).
- Triage of the new rows is sequence 2, called once per complaint inside `POST /triage/pending`.
- Recovery steps are in [runbooks/ingestion-failed.md](../operations/runbooks/ingestion-failed.md).

---

## 2. Single complaint triage

`vsia.agent.triage()` as called by `POST /triage` (FR-4, FR-6; ADR-0060, ADR-0007, ADR-0061, ADR-0062,
ADR-0063). The same function runs for `POST /triage/pending`, `vsia triage` and the evaluation harness.

```mermaid
sequenceDiagram
  autonumber
  participant C as Caller (n8n, CLI or eval)
  participant A as VSIA API
  participant G as Triage workflow (vsia.agent)
  participant R as Guardrails
  participant T as Tools (vsia.tools)
  participant X as Retrieval store
  participant K as Baseline classifier
  participant L as LLM gateway (vsia.llm)
  participant P as LLM provider
  participant F as Confidence scorer
  participant D as DB

  C->>A: POST /triage with odi_number (bearer)
  A->>D: load_complaint: SELECT complaints WHERE odi_number
  D-->>A: Complaint
  A->>G: triage(complaint, provider, run_id api-...)
  G->>R: redact(summary)
  R-->>G: redacted text and counts per PII type
  G->>R: detect_injection(summary)
  R-->>G: score and rule ids
  G->>T: recall_lookup(make, model, model_year)
  T->>D: SELECT recalls WHERE make and model_year, match model family
  T-->>G: recalls covering the vehicle
  G->>T: recall_search(redacted text, vehicle)
  T->>X: search recalls and recall_docs with vehicle_keys filter
  X-->>T: hits per namespace, RRF fused per campaign
  T-->>G: up to 5 campaign hits with scores
  G->>G: merge candidates, keep at most 12, signals n_candidates, retrieval_top_score
  G->>K: predict_proba(redacted text)
  K-->>G: probability per component
  G->>L: complete_json(system prompt, user message, TriageOutput, purpose triage, prompt triage-v1)
  L->>P: request with cleaned JSON schema
  P-->>L: JSON text and token counts
  alt reply fails Pydantic validation
    L->>P: repair retry with the validator message appended
    P-->>L: JSON text
  end
  L->>D: INSERT llm_calls (provider, model, tokens, cost, latency, ok, ref_id, no prompt text)
  alt valid reply
    L-->>G: LLMResult(TriageOutput, attempts)
  else second invalid reply or provider error
    L-->>G: LLMError
    G->>G: use classifier output, signal llm_error, mark for review
  end
  G->>G: normalise component to taxonomy, de-duplicate secondary components
  G->>R: validate_citations(cited campaigns, candidate set)
  R-->>G: grounded campaigns
  G->>G: keep only campaigns sharing a component, count citations_dropped
  G->>G: severity rule: crash, fire, injury or death sets S1, keep llm_severity
  G->>F: score(signals, provider)
  F-->>G: confidence and method (logreg_calibrator or fallback_weights)
  G->>G: route review if confidence below threshold, injection flagged or LLM failed, else auto
  G->>D: INSERT triage_records, and review_queue (pending) when route is review
  G-->>A: TriageRecord
  A-->>C: 200 TriageRecord JSON
```

Notes:
- Redaction happens before any text reaches the classifier, the embedding model, the search query or the
  LLM. `components_raw` and `component_primary` are never in the prompt (ADR-0005).
- `recall_search` redacts the query again inside `search_recalls_for_complaint`; `redact` is idempotent.
- Latency is dominated by the single LLM call (ADR-0060). Measured values: measured in docs/evaluation/
  (pending).

---

## 3. Low-confidence routing to human review, and the decision becoming a label

FR-5; ADR-0061, ADR-0064, ADR-0073, ADR-0075. The human review operating procedure (queue service level,
audit sampling, label use) is in [hitl/review-workflow.md](../hitl/review-workflow.md).

```mermaid
sequenceDiagram
  autonumber
  participant G as Triage workflow
  participant D as DB
  participant N2 as n8n workflow 02
  participant A as VSIA API
  participant W as Notify webhook
  actor U as Analyst
  participant S as Streamlit review page
  participant V as vsia.review

  G->>D: INSERT triage_records (route review)
  G->>D: INSERT review_queue (status pending, reason)
  Note over G,D: evaluation runs call triage with enqueue False, so they never reach the queue
  loop every hour
    N2->>A: GET /review/pending
    A->>V: pending(limit 50)
    V->>D: SELECT queue JOIN triage_records JOIN complaints ORDER BY confidence ASC
    V-->>A: pending rows
    A-->>N2: list
    opt backlog above VSIA_REVIEW_BACKLOG_THRESHOLD (default 25)
      N2->>W: backlog message
    end
  end
  U->>S: open Human review page
  S->>V: pending()
  V->>D: SELECT pending items
  S-->>U: lowest confidence first, redacted text, model output, review reasons, candidate recalls
  U->>S: accept, or correct component, severity, campaigns (from candidates only)
  alt writes allowed (not VSIA_READONLY, not demo mode)
    S->>V: decide(ReviewDecision)
    V->>D: SELECT oldest pending item for the complaint
    V->>D: UPDATE review_queue SET status accepted or corrected, resolved_at
    V->>D: INSERT labels (source review, reviewer, note)
    V-->>S: decision
    S->>S: clear caches so stats update
  else read-only
    S-->>U: form disabled with an explanation
  end
  Note over U,A: alternative path: a form posts to n8n webhook vsia-review, which forwards to POST /review/decision
```

Notes:
- The label row keeps the final component, severity and campaigns. An accepted item copies the triage
  record's values; a corrected item uses the reviewer's values.
- `labels` with `source = review` are the input for refitting the calibrator on reviewed labels
  (ADR-0061, "Revisit when"); that refit is not implemented yet.

---

## 4. RAG chat through the Open WebUI pipe, n8n and the API

FR-9; ADR-0065, ADR-0076, ADR-0077.

```mermaid
sequenceDiagram
  autonumber
  actor U as Team member
  participant O as Open WebUI and vsia_pipe
  participant N4 as n8n workflow 04
  participant A as VSIA API
  participant Q as vsia.rag
  participant L as LLM gateway
  participant X as Retrieval store
  participant D as DB

  U->>O: question
  O->>O: take the latest user message only (single turn)
  O-->>U: status event Searching complaints and recalls
  O->>N4: POST /webhook/vsia-chat with question, messages, user_id (n8n bearer)
  N4->>N4: header auth check
  N4->>A: POST /chat with question (API bearer credential)
  A->>Q: answer(question)
  Q->>L: complete_json(QueryPlan, purpose rag_plan, question wrapped as untrusted)
  L-->>Q: intent, make, model_year, component, search_text
  alt intent out_of_scope
    Q-->>A: fixed refusal, refused true, no retrieval
  else lookup or aggregate
    Q->>X: search_complaints(search_text, filter make and model_year, top 8)
    X-->>Q: redacted complaint hits
    Q->>X: search recalls and recall_docs (top 4 each)
    X-->>Q: recall hits
    opt intent aggregate
      Q->>D: SELECT component_primary, make, count GROUP BY (filters from the plan)
      D-->>Q: count table
    end
    Q->>L: complete_json(ChatAnswer, purpose rag_answer, context and question)
    L-->>Q: answer, citations, refused
    Q->>Q: validate_citations against retrieved ids, drop the rest
    Q-->>A: answer, citations, refused, plan, latency_ms
  end
  A-->>N4: 200 JSON
  N4-->>O: answer, citations, refused
  O-->>U: source event per citation, answer with numbered Sources (recall links to nhtsa.gov)
  Note over N4,O: if the API fails, workflow 04 responds 502 with a fallback answer and the pipe shows it
```

Notes:
- Each LLM call above writes one `llm_calls` row (`rag_plan`, `rag_answer`) with `prompt_version`
  `rag-v1` and no `ref_id`.
- The aggregate path counts NHTSA-coded `component_primary`. This is reference data shown to the chat model,
  not triage input, so it does not break the label-leakage rule for triage (ADR-0005), but the
  [threat model](../security/threat-model.md) should note it.

---

## 5. Weekly forecast and spike alert

FR-7; ADR-0081. n8n workflow `03_weekly_forecast_retrain.json` calls the API; the same code runs from the
CLI as `python -m pipelines.forecast all`.

```mermaid
sequenceDiagram
  autonumber
  participant S as n8n Schedule Monday 07:00
  participant N3 as n8n workflow 03
  participant A as VSIA API
  participant F as pipelines.forecast
  participant D as DB
  participant M as MLflow
  participant W as Notify webhook

  S->>N3: trigger (cron 0 7 * * 1)
  N3->>A: POST /forecast/run (bearer, 30 minute timeout)
  A->>F: cmd_train(force False)
  F->>D: SELECT date_filed, component_primary FROM complaints
  F->>F: weekly panel (Monday weeks, pool small components into OTHER), data fingerprint
  F->>M: get model version by alias vsia-complaint-forecaster@champion
  alt champion has the same data_fingerprint
    F-->>A: None (retrain skipped)
  else new data or configuration
    F->>F: backtest 7 candidates over 3 rolling origins plus a 12-week holdout
    F->>M: parent run train-timestamp, nested run per candidate (params, metrics, artifacts, sklearn model)
    F->>M: register lowest validation WAPE model, set alias champion and tags
    F-->>A: summary, run ids, champion
  end
  A->>F: cmd_detect()
  F->>M: load models:/vsia-complaint-forecaster@champion
  F->>D: SELECT complaints panel again
  F->>F: 1-step forecasts for weeks after the training window, 4 future weeks, 90 percent interval
  F->>F: flag spikes: actual above upper bound and at least 3 complaints
  F->>D: SELECT recalls report dates (weak check: recall within 28 days)
  F->>D: DELETE then INSERT forecasts and spike_alerts for those weeks (run_id = champion MLflow run id)
  F-->>A: alerts, run_id
  A-->>N3: run_id, retrained, alerts (current flag), current_alerts
  alt alerts present
    N3->>W: formatted spike alerts
  end
  Note over A,N3: the API returns 409 when the pipeline cannot run yet (no champion, changed component set, no new weeks)
```

Notes:
- The headline forecast metric is component-level WAPE on 1-step holdout forecasts; MAPE and the ratio to
  seasonal naive are also logged. Results: measured in docs/evaluation/ (pending); the MLflow store on the
  laptop holds one failed `train-20261019T054635Z` parent run and no registered champion at the time of
  writing.

---

## 6. Recall document parsing and indexing

FR-2, FR-3; ADR-0031, ADR-0032, ADR-0033, ADR-0030. These are operator-run batch jobs, not scheduled by n8n.

```mermaid
sequenceDiagram
  autonumber
  actor Op as Operator
  participant FD as scripts/fetch_recall_docs.py
  participant H as NHTSA (safetyIssues API, static.nhtsa.gov)
  participant FS as data/docs (PDFs, manifest)
  participant DP as vsia.documents
  participant L as LLM gateway
  participant D as DB
  participant BI as scripts/build_index.py
  participant E as Embedder (Ollama nomic-embed-text)
  participant X as Vector store (local files or Pinecone)

  Op->>FD: run with limit 80
  FD->>D: SELECT complaints and recalls, rank campaigns by complaint volume, round-robin by component
  loop each selected campaign (throttled about 3 per second)
    FD->>H: GET safetyIssues byNhtsaId
    H-->>FD: associatedDocuments
    FD->>H: download latest Part 573 report and earliest owner letter (size limits)
    FD->>FS: write PDF, append manifest entry with SHA-256
  end
  Op->>DP: python -m vsia.documents
  DP->>FS: load manifest (Part 573 reports first)
  DP->>D: SELECT parsed source_urls and campaigns with a valid Part 573 extraction
  loop each document not yet parsed
    DP->>DP: parse_pdf: LlamaParse if key, else pypdf, tesseract OCR if under 200 characters
    DP->>DP: redact(markdown)
    DP->>DP: extract_rules (Part 573 labels or owner-letter questions)
    alt rules fail and campaign already covered by a Part 573 extraction
      DP->>DP: method covered_by_part573
    else rules fail and LLM allowed
      DP->>L: complete_json(RecallDocExtraction, purpose recall_extraction)
      L-->>DP: fields (campaign number and URL forced from the manifest)
    end
    DP->>D: DELETE then INSERT recall_documents (redacted markdown, extraction, valid flag)
  end
  Op->>BI: python scripts/build_index.py
  BI->>D: SELECT recalls, recall_documents, complaints
  BI->>BI: recall records per campaign x vehicle, 800-token chunks with 100 overlap, redacted complaint narratives
  BI->>E: embed documents with prefix search_document (local store only)
  E-->>BI: 768-d vectors
  BI->>X: upsert per namespace (recalls, recall_docs, complaints)
  X-->>BI: counts, info.json with embedding model and timestamp
```

Notes:
- Measured at build time (ADR-0031, ADR-0032): 150 documents, 481 pages, 140 via pypdf and 10 via OCR, 799
  redactions; all 80 Part 573 reports extracted by rules, 8 of 70 owner letters by rules and 62 covered by
  their Part 573, 0 LLM calls.
- Index sizes (ADR-0033, `data/index/*/info.json`): recalls 407, recall_docs 352. The complaints
  namespace was being built at the time of writing.
- On Pinecone, embedding is done by the index (`llama-text-embed-v2`); vectors from the two stores are not
  comparable, so switching stores is a full re-index (ADR-0030).
