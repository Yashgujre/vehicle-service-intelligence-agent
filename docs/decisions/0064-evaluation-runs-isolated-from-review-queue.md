# ADR-0064: Evaluation runs are tagged and never enter the human review queue

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** Triage agent, evaluation (`eval/run_eval.py`)
- **PRD link:** FR-5 (review queue), FR-12 (evaluation)

## Context

The evaluation runs the full triage pipeline over 500 complaints per provider. If those results entered
the review queue, reviewers would see duplicates of the same complaint from several providers, and review
metrics would mix production and test traffic.

## Decision

1. `triage(..., enqueue=False)` for evaluation; records are still persisted with a `run_id` prefixed
   `eval-`, so dashboards can include or exclude them.
2. Evaluation predictions are also written to `data/eval/{split}_{provider}.jsonl`, which makes runs
   resumable and re-scorable without new LLM calls.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Persist with run id, never enqueue (chosen) | Full audit trail; clean queue | Dashboards must filter by run id |
| B. Do not persist evaluation runs | Clean database | Loses the trace for debugging failures |
| C. Separate database for evaluation | Strong isolation | Two schemas to keep in step |

## Revisit when

Evaluation volume makes the main tables large enough to slow dashboard queries.
