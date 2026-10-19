# ADR-0025: Accept a citation only if it is in the set of ids retrieved for that request

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** guardrails (`guardrails.validate_citations`), triage agent, RAG chat
- **PRD link:** FR-4 (recall links with citations), FR-9 (cited answers), FR-11

## Context

Both LLM paths return identifiers: triage returns recall campaign numbers (`RecallMatch.campaign_number`),
and RAG chat returns ids such as `recall:23V168000` and `complaint:11770228`. A model can produce an id
from memory, from text inside the complaint, or by inventing one in the right format (OWASP
LLM09:2025 Misinformation). A schema pattern (`^\d{2}[VEITC]\d{6}$`) proves only the format. ADR-0063
adds a triage-specific component-overlap rule on top of this decision.

## Decision

`validate_citations(cited, allowed)` keeps only ids present in `allowed`, the set the tools or retriever
returned for this request:

- triage: the union of `recall_lookup` and `recall_search` campaign numbers (`vsia/agent.py` line 135);
- RAG chat: the complaint and recall ids placed in the context block (`vsia/rag.py` line 116).

Matching ignores case, spaces and dashes and a leading `NHTSA`, `ODI`, `CAMPAIGN` or `RECALL`, and maps
the short form `22V702` to `22V702000`. It returns the allowed spelling, de-duplicated, in the model's
order. Dropped triage citations are counted in `confidence_signals.citations_dropped`.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Post-filter against the retrieved set (chosen) | Deterministic; provider-agnostic; catches invented and memory-sourced ids; cheap | Drops a correct id the model knew but retrieval missed |
| B. Validate against the full `recalls` table | Keeps correct ids from model memory | Accepts real campaigns for the wrong vehicle |
| C. Constrain the output schema to an enum of allowed ids per request | Model cannot emit an ungrounded id | Schema changes every call; an empty candidate list needs a special case; forced choice can push the model to pick something |
| D. LLM judge verifies each citation | Can judge relevance, not only membership | Doubles cost; a small judge is unreliable; still needs A for membership |

## Trade-offs accepted

Retrieval recall caps citation recall: a correct recall the tools did not return can never be cited. In
RAG chat only the `citations` list is filtered; bracketed ids inside the free-text `answer` are not
removed (risk R-26).

## Consequences

- Tests: `test_validate_citations_drops_ungrounded_ids`, `test_validate_citations_empty_inputs`.
- Retrieval recall at k and citation precision become the metrics that show the cost of this rule:
  measured in docs/evaluation/ (pending).
- The native n8n workflow 05 does not apply this rule; its system prompt only asks the model to cite
  tool results.

## Revisit when

- Evaluation shows a material share of correct recall matches dropped because retrieval missed them
  (improve retrieval first), or
- providers support per-request enum constraints cheaply and consistently (option C), or
- inline citations in chat answers need to be enforced (extend the filter to the `answer` text).
