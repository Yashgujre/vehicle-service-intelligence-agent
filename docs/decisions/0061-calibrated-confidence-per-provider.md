# ADR-0061: Routing confidence is a calibrated composite score per provider, threshold tuned for auto-route accuracy

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** Confidence and routing (`src/vsia/confidence.py`, `eval/run_eval.py`)
- **PRD link:** FR-5 (route low-confidence items to human review), FR-6 (per-model comparison), success metric on auto-routed accuracy

## Context

FR-5 routes "low-confidence" triage results to a human. An LLM's self-reported confidence is poorly
calibrated, more so for small local models, and differs by provider. A fixed threshold on it would
send either too much or too little to review.

## Decision

1. Signals per complaint: `llm_confidence`, `clf_prob_of_llm_label` (independent TF-IDF classifier's
   probability for the LLM's label), `clf_max_prob`, `agree` (classifier top label equals LLM label),
   `retrieval_top_score`, `schema_retry`.
2. A logistic-regression calibrator per provider maps signals to P(component correct), fitted on the
   300-complaint calibration split (never on the gold split).
3. The threshold per provider is the one that maximises auto-route coverage subject to at least 90%
   accuracy on auto-routed items in the calibration split; stored in `data/models/routing_{provider}.json`.
4. Until a calibrator exists, a fixed weighted blend is used and recorded as `confidence_method=fallback_weights`.
5. Injection suspicion or an LLM failure routes to review regardless of the score.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Calibrated composite per provider (chosen) | Threshold means something measurable; uses an independent model as a check | Needs a labelled calibration split per provider |
| B. LLM self-reported confidence with fixed 0.70 | Simple; matches PRD wording | Uncalibrated; not comparable across providers |
| C. Token log-probabilities | Principled | Not available from all providers with structured output |
| D. Self-consistency (sample N times) | Strong signal | N times the cost and latency |

## Trade-offs accepted

The calibration split labels are NHTSA-coded components (silver labels), so "correct" means agreement
with NHTSA coding. The 90% target is a design choice, not a PRD number.

## Consequences

Every triage record stores its signals and the method used, so thresholds can be re-tuned from stored
data without re-running the LLM.

## Revisit when

Human review decisions accumulate (refit the calibrator on reviewed labels), or a provider exposes
log-probabilities with structured output.
