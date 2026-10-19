# ADR-0062: Owner-reported crash, fire, injury or death forces severity S1; the model's raw severity is kept and measured

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** Triage agent (`src/vsia/agent.py`)
- **PRD link:** FR-4 (severity classification), FR-11 (guardrails)

## Context

Under-rating a safety-critical complaint is the costliest triage error. NHTSA complaints carry structured
flags for crash, fire, injuries and deaths. A model can read "minor fender bender" and rate S3.

## Decision

1. If the complaint's crash or fire flag is set, or injuries or deaths are above zero, severity is S1.
2. The LLM's own severity is stored as `signals.llm_severity`; `severity_rule_override=true` marks
   overrides.
3. The evaluation reports S1 precision and recall of the raw LLM severity, so model quality is not hidden
   by the rule.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Deterministic rule overrides, raw value kept (chosen) | Zero false negatives on flagged items; auditable | May over-rate (a crash unrelated to a defect) |
| B. Trust the LLM | One source of truth | Unbounded under-rating risk |
| C. Rule only, no LLM severity | Simple | No severity for the roughly 90% of complaints without flags |

## Trade-offs accepted

Over-rating is accepted: an S1 that is not truly critical costs a reviewer a few minutes; an under-rated
fire costs far more. 930 of 10,303 ingested complaints carry at least one flag.

## Revisit when

Reviewer decisions show the rule over-rates more than a set share of flagged items.
