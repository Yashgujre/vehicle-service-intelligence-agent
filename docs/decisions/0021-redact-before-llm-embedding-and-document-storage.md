# ADR-0021: Redact at every use point (LLM, embedding, search, display, logs) and before storing parsed documents

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** guardrails, parsing, retrieval (`vsia.agent`, `vsia.retrieval`, `vsia.documents`, `scripts/build_index.py`)
- **PRD link:** FR-2, FR-3, FR-4, FR-11, NFR privacy

## Context

ADR-0020 defines what `redact()` removes. This record decides **where** it runs. Text flows to four
kinds of consumer: LLM providers (Anthropic, OpenAI, Ollama), embedding models and vector stores (Ollama
`nomic-embed-text`, Pinecone integrated embedding, which stores the record text), screens (dashboard,
chat), and logs. Two sources differ:

- Complaint narratives arrive from the NHTSA API, are already public, and are the evaluation corpus.
  Redaction rules will improve over time.
- Recall PDFs are parsed into markdown that is derived data; owner letters carry sample names and
  addresses, and Part 573 reports carry company phone numbers.

## Decision

1. Store complaint narratives as received (`complaints.summary`), and redact at every point where text
   leaves the database for a consumer: before the triage LLM call, the recall search and the classifier
   (`vsia/agent.py` line 101); in every vector search function (`vsia/retrieval.py`
   `search_recalls_for_complaint`, `search_complaints`, `search_sources`); before indexing
   (`scripts/build_index.py` `complaint_records`); in `GET /search`; on dashboard reads and demo export
   (`app/data.py`, `scripts/export_demo_snapshot.py`); in span logs (`vsia/observability.py` `_scrub`).
2. Redact parsed recall documents **before storage** (`vsia/documents.py` `process`), so the stored
   markdown, the extraction input, the LLM fallback and the index all see the same redacted text.
3. Do not redact the `recalls` API text (summary, consequence, remedy): it is manufacturer text whose
   phone numbers are public hotlines.
4. Never log prompt or reply text; `llm_calls` holds metadata only.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Raw complaints at rest, redact at each use point; documents redacted before storage (chosen) | Rules can be improved and re-applied without re-ingesting; the stored corpus matches the public source; derived document text never holds PII | Every new consumer must remember to call `redact()`; a missed call is a leak |
| B. Redact once at ingestion, store only redacted text | One choke point; impossible to forget downstream | Rule improvements need re-ingestion; the evaluation corpus diverges from the public record; redaction false positives become permanent |
| C. Redact only before LLM calls | Smallest change | Unredacted text would be embedded and stored as record text in Pinecone, a third party |
| D. Store raw and redacted columns side by side | One choke point and the raw copy | Schema change to a contract table (`schemas.py`, data contracts); two columns to keep in sync |

## Trade-offs accepted

The guarantee depends on discipline at each call site rather than on the storage layer. Writing the
security documentation on 2026-10-19 found two call sites that do not redact: the RAG chat question
(`vsia/rag.py` lines 54 and 109) and the heuristic fallback's `extracted.symptom`
(`vsia/agent.py` line 88). Both are tracked as risks R-03 and R-04 in
`docs/security/ai-risk-register.md`.

## Consequences

- AGENTS.md rule 4 is the policy; `docs/security/pii-handling.md` section 5 is the inventory of call
  sites and must be updated with every new consumer.
- Measured on 2026-10-19: the 150 stored recall documents contain 799 placeholders and zero residual
  matches when `redact()` is re-run, confirming redaction before storage.
- Chat history stored by Open WebUI and n8n execution data are outside this policy (risk R-05).

## Revisit when

- A third call site is found without redaction (move to option D or add a test that fails on any
  consumer reading `complaints.summary` without `redact()`), or
- a non-public data source is added (redact at ingestion, option B), or
- the redaction rules have been stable for two releases and re-ingestion becomes cheap.

## Update (2026-10-19)

The RAG chat call site named under "Trade-offs accepted" now redacts: `answer()` in `src/vsia/rag.py`
calls `guardrails.redact()` on the question (line 76) before the plan call, retrieval and the answer call.
Risk R-03 and gap G1 are closed. The heuristic fallback's `extracted.symptom` (risk R-04) is unchanged.
