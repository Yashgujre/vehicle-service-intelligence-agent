# Agent tools: contracts

- **Status:** Current as of 2026-10-19
- **Owner:** AI workflow engineer
- **Code:** `src/vsia/tools.py` (Python tools and specs), `workflows/n8n/05_triage_agent_native.json`
  (n8n HTTP tools), `src/vsia/api.py` `search` (endpoint behind the n8n search tool)
- **Format:** one contract per tool with name, description, input schema, output schema, errors, side
  effects, rate limits and approvals, following the MCP tool definition and Anthropic tool-design
  guidance summarised in `docs/research/01_documentation_process_research.md` section (c) topic 6
- **Related:** ADR-0060 (fixed workflow, not a ReAct loop), ADR-0063 and ADR-0025 (citations restricted
  to tool results), ADR-0075 (n8n-native agent variant), ADR-0026 and ADR-0077 (auth)

## 1. How tools are used

| Path | Who decides to call a tool | Tools |
|---|---|---|
| Python triage agent (`vsia.agent.triage`, system of record) | Deterministic code. Every complaint calls both tools once, before the single LLM call. The model never selects or parameterises a tool | `recall_lookup`, `recall_search` |
| n8n native agent (workflow 05, demo and comparison variant, inactive by default) | The model, through n8n's AI Agent node, at most 5 iterations | "NHTSA Recalls Tool", "VSIA Search Tool" |

All four tools are **read-only**. None writes to a database, sends a message or changes external state.
Tool results are treated as untrusted data: in the Python path they become the `<candidate_recalls>`
block and the allowed set for citation grounding (`guardrails.validate_citations`).

## 2. `recall_lookup` (Python)

| Field | Value |
|---|---|
| Function | `vsia.tools.recall_lookup(make, model, model_year, live=False) -> list[dict]` |
| Spec constant | `RECALL_LOOKUP_SPEC`, registered name `nhtsa_recall_lookup` |
| Description (from the spec) | "List NHTSA recall campaigns that cover a specific vehicle (make, model, model year). Returns campaign number, component, summary and remedy. Read-only." |
| Called by | `vsia.agent._candidates` (`src/vsia/agent.py` line 48) |

Input schema (as declared in `RECALL_LOOKUP_SPEC`):

```json
{
  "type": "object",
  "required": ["make", "model", "model_year"],
  "properties": {
    "make": {"type": "string"},
    "model": {"type": "string"},
    "model_year": {"type": "integer"}
  }
}
```

`live` is a Python-only argument, not part of the spec. Matching rules: `make` is upper-cased;
`model_year` must equal the stored year; `model` matches through `model_family()` normalisation (for
example `MUSTANG MACH-E BEV` and `MUSTANG MACH E` are the same family).

Output schema (one object per campaign, de-duplicated by campaign number):

```json
{
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "campaign_number": {"type": "string", "description": "NHTSA campaign, e.g. 23V168000"},
      "component": {"type": ["string", "null"], "description": "NHTSA component_raw, else component_primary"},
      "summary": {"type": ["string", "null"]},
      "remedy": {"type": ["string", "null"]},
      "report_date": {"type": "string", "description": "ISO date or empty string"}
    }
  }
}
```

| Aspect | Contract |
|---|---|
| Data source | Local `recalls` table (refreshed by ingestion, workflow 01). With `live=True`, also `GET https://api.nhtsa.gov/recalls/recallsByVehicle`, merged without overwriting local rows |
| Errors | Database errors are **not caught** and propagate to the caller (a triage request then fails). With `live=True`, any NHTSA error is swallowed and only local rows are returned. An unknown vehicle returns `[]` |
| Side effects | None. Read-only `SELECT`; optional read-only HTTPS `GET` |
| Rate limits | Local: none. Live: NHTSA client retries 429 and 5xx up to 4 attempts with exponential backoff (max 20 s wait), 60 s timeout (`src/vsia/nhtsa.py`); no client-side throttle in this function. The triage agent uses `live=False` |
| Approvals | None required (read-only). Human approval applies to the triage output through the review queue, not to the tool call |
| Security notes | Output text (summary, remedy) is public NHTSA text and is inserted into the prompt without `wrap_untrusted` (risk R-09). NHTSA's coded component appears in the candidate list; this is the recall's component, not the complaint's ground-truth label, so it does not breach the label-leakage rule (ADR-0005) |

## 3. `recall_search` (Python)

| Field | Value |
|---|---|
| Function | `vsia.tools.recall_search(query, make, model, model_year, top_k=5) -> list[RetrievalHit]` |
| Spec constant | `RECALL_SEARCH_SPEC`, registered name `recall_search` |
| Description (from the spec) | "Semantic + keyword search over recall records and parsed recall documents, filtered to the vehicle. Use the complaint's symptom description as the query. Read-only." |
| Implementation | `vsia.retrieval.search_recalls_for_complaint`: searches namespaces `recalls` and `recall_docs` with a `vehicle_keys` filter (make, model family, model year), fuses rankings by reciprocal rank fusion at campaign level, one hit per campaign |
| Called by | `vsia.agent._candidates` with the **redacted** narrative truncated to 2,000 characters and `top_k` from `config/settings.yaml` (`retrieval.top_k: 5`); also `GET /search` in the API |

Input schema (as declared in `RECALL_SEARCH_SPEC`):

```json
{
  "type": "object",
  "required": ["query", "make", "model_year"],
  "properties": {
    "query": {"type": "string"},
    "make": {"type": "string"},
    "model": {"type": "string"},
    "model_year": {"type": "integer"},
    "top_k": {"type": "integer", "default": 5}
  }
}
```

The Python signature requires `model` positionally, while the spec lists it as optional (see section 6).
The query is redacted again inside `search_recalls_for_complaint` (`src/vsia/retrieval.py` line 526).

Output schema (`vsia.schemas.RetrievalHit`, one per campaign):

```json
{
  "type": "array",
  "items": {
    "type": "object",
    "required": ["id", "namespace", "score", "text"],
    "properties": {
      "id": {"type": "string", "description": "campaign number"},
      "namespace": {"const": "recalls"},
      "score": {"type": "number", "description": "RRF score, not comparable across requests"},
      "text": {"type": "string", "description": "representative record text (API record preferred)"},
      "metadata": {
        "type": "object",
        "description": "campaign_number, component, sources (record ids), best_dense_cosine, representative, plus stored record fields"
      }
    }
  }
}
```

| Aspect | Contract |
|---|---|
| Data source | Vector store selected by `VSIA_VECTOR_STORE`: local (Ollama `nomic-embed-text` vectors plus BM25) or Pinecone (`llama-text-embed-v2` integrated embedding, dense only) |
| Errors | Every exception (import failure, Ollama or Pinecone unavailable) is caught and returns `[]`. The agent then sees fewer or no candidates; `n_candidates` and `retrieval_top_score` in `confidence_signals` show it |
| Side effects | None. Embeds the query (Ollama call or Pinecone inference) and reads the index |
| Rate limits | Local: none. Pinecone: provider plan limits; no client-side limit in this code |
| Approvals | None required (read-only) |
| Security notes | Query is redacted (ADR-0021); results are untrusted retrieved text; returned campaign numbers form part of the citation allow-list, so a poisoned index entry could add a candidate (threat E-T1) |

## 4. "NHTSA Recalls Tool" (n8n, workflow 05)

| Field | Value |
|---|---|
| Node | `NHTSA Recalls Tool`, type `n8n-nodes-base.httpRequestTool` version 4.5 (type and version **inferred**, not verified against a running instance; see `workflows/n8n/README.md`) |
| Tool description (as given to the model) | "Look up official NHTSA recalls for one vehicle. Returns campaign numbers, components, summaries and remedies. Inputs: make, model, modelYear." |
| Request | `GET https://api.nhtsa.gov/recalls/recallsByVehicle?make=&model=&modelYear=`; no authentication |
| Called by | The n8n AI Agent node, when the model chooses to (the system message tells it to call the tool first) |

Input schema (parameters filled by the model through `$fromAI`):

| Parameter | Type | Description given to the model |
|---|---|---|
| `make` | string | "Vehicle make, e.g. FORD" |
| `model` | string | "Vehicle model as written in recalls, e.g. MUSTANG MACH E" |
| `modelYear` | number | "Four-digit model year" |

Output: the NHTSA response body, passed to the model unmodified. The fields VSIA relies on elsewhere
(`vsia.nhtsa.normalize_recall`) are `results[].NHTSACampaignNumber`, `Make`, `Model`, `ModelYear`,
`Manufacturer`, `ReportReceivedDate` (DD/MM/YYYY), `Component`, `Summary`, `Consequence`, `Remedy`,
`parkIt`, `parkOutSide`, `overTheAirUpdate`.

| Aspect | Contract |
|---|---|
| Errors | `neverError: true`: NHTSA answers "no match" with HTTP 400 and an empty result; that body is passed to the model instead of failing the node. Timeout 20,000 ms |
| Side effects | None (public read-only GET) |
| Rate limits | NHTSA publishes no limit that this repository records; the Python client treats 429 as retryable. The agent's `maxIterations: 5` bounds the number of calls per execution |
| Approvals | None. No human approval step before the call; the workflow's database write is a fixed node, not a tool |
| Security notes | Parameters are model-chosen, so a prompt-injected complaint could steer the query to another vehicle; the impact is a wrong candidate list, not a write. Tool output enters the model context without wrapping, and the native variant has no citation grounding against it (risk R-22) |

## 5. "VSIA Search Tool" (n8n, workflow 05)

| Field | Value |
|---|---|
| Node | `VSIA Search Tool`, type `n8n-nodes-base.httpRequestTool` version 4.5 (inferred) |
| Tool description (as given to the model) | "Hybrid search over recall records and parsed recall documents for this vehicle. Inputs: q (symptom keywords), make, model, model_year." |
| Request | `GET {VSIA_API_BASE_URL or http://vsia-api:8000}/search?q=&make=&model=&model_year=&top_k=5` with the Header Auth credential "VSIA API bearer" (`Authorization: Bearer <VSIA_API_TOKEN>`) |
| Server side | `vsia.api.search`: redacts `q`; with `make`, `model` and `model_year` and no `namespace` it runs `tools.recall_search` (section 3) |

Input schema (parameters filled by the model through `$fromAI`, except `top_k`):

| Parameter | Type | Description given to the model |
|---|---|---|
| `q` | string | "Short symptom keyword query" |
| `make` | string | "Vehicle make" |
| `model` | string | "Vehicle model" |
| `model_year` | number | "Four-digit model year" |
| `top_k` | fixed | `5` |

Output: JSON array of `RetrievalHit` objects as in section 3.

| Aspect | Contract |
|---|---|
| Errors | HTTP 401 if the credential is missing or wrong; HTTP 422 if a parameter has the wrong type; any search failure returns `[]` (section 3). `neverError` is not set, so HTTP errors surface to the agent as tool errors. Timeout 20,000 ms |
| Side effects | None |
| Rate limits | None in the API; bounded per execution by `maxIterations: 5` |
| Approvals | None (read-only) |
| Security notes | The model chooses `q`; the API redacts it before embedding. The model could request another vehicle's recalls; impact is limited to the candidate list |

## 6. Inconsistencies noted

| Location | Issue |
|---|---|
| `src/vsia/tools.py` line 31 | The lookup tool's registered name is `nhtsa_recall_lookup`, while the function and the rest of the documentation call it `recall_lookup` |
| `src/vsia/tools.py` lines 64 and 71 | `RECALL_SEARCH_SPEC` marks `model` optional; `recall_search()` requires it |
| `src/vsia/tools.py` line 33 | The lookup spec description omits `report_date`, which the function returns |
| `src/vsia/tools.py` lines 44 to 46 | `recall_lookup` does not catch database errors, unlike `recall_search`, which returns `[]` on any error |
| `workflows/n8n/05_triage_agent_native.json` | Both HTTP tool node types are inferred and unverified (README "Known gaps") |
