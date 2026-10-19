# ADR-0063: Recall matches must be grounded in the candidate list and share a component with the triage result

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** Triage agent (`src/vsia/agent.py`), guardrails (`validate_citations`)
- **PRD link:** FR-4 (every recall match cites a campaign number), FR-11 (guardrails)

## Context

In the first smoke tests the local model attached recalls that covered the vehicle but not the problem
(a seat-belt recall on a power-loss complaint), and occasionally a campaign number not in its context.
A wrong recall match sends a service advisor to the wrong remedy.

## Decision

1. Citation grounding: a cited campaign must be in the candidate list the tools returned; others are
   dropped (`guardrails.validate_citations`).
2. Component overlap: a kept match must share at least one component with the triaged primary or secondary
   components (config `retrieval.require_component_overlap: true`).
3. Dropped matches are counted in `signals.citations_dropped`.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Grounding plus component overlap (chosen) | Removes fabricated and off-topic matches deterministically | Misses a true match when the recall's NHTSA component differs from the triage label |
| B. Grounding only | Fewer false drops | Off-topic matches pass |
| C. Second LLM call to verify each match | Semantic check | Doubles cost; small model unreliable as a judge |

## Trade-offs accepted

Recall-match recall is traded for precision. The evaluation reports match hit rate against silver recall
labels so the cost of this rule is visible.

## Revisit when

Match recall in the evaluation is materially lower than retrieval recall@5 (the rule is dropping true
matches).
