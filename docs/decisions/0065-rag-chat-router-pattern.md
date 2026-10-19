# ADR-0065: RAG chat routes each question (lookup, aggregate, out of scope) before retrieval

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** RAG chat (`src/vsia/rag.py`), Open WebUI pipe
- **PRD link:** FR-9 (chat over complaints and recalls with citations, refuses out-of-scope questions)

## Context

Chat questions are of two kinds. "Is there a recall for loose subframe bolts on the 2021 Mach-E?" is a
lookup that retrieval answers. "Which component had the most complaints for the IONIQ 5 last quarter?"
is a count; top-5 retrieved passages cannot answer it, and a model will guess.

## Decision

1. A first structured LLM call produces a `QueryPlan`: intent (`lookup`, `aggregate`, `out_of_scope`) and
   filters (make, model year, component).
2. `lookup`: hybrid retrieval over complaints, recalls and recall documents with the filters.
3. `aggregate`: the same retrieval plus SQL counts from the database, passed to the model as a table.
4. `out_of_scope`: a fixed refusal, no retrieval.
5. The answer call must cite retrieved ids; citations not in the retrieved set are removed.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Router then retrieval or SQL (chosen) | Counts come from SQL, not the model; scope control | Two LLM calls per question |
| B. Retrieval only | One call | Wrong answers to count questions |
| C. Text-to-SQL agent | Flexible analytics | SQL injection and correctness risk with a 3B model |

## Trade-offs accepted

The aggregate path supports a fixed breakdown (complaint counts by component and make, filtered by make, model year and component), not arbitrary
SQL.

## Revisit when

Users ask for breakdowns outside the fixed set often enough to justify a constrained text-to-SQL tool.
