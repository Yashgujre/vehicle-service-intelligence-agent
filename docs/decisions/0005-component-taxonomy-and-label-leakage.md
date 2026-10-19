# ADR-0005: Use NHTSA's coded components as the taxonomy and as ground truth, never as model input

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer
- **Component:** cross-cutting (data, evaluation)
- **PRD link:** Goal 1, FR-4, FR-12, Success metric "component classification accuracy >= 85%"

## Context

Every NHTSA complaint carries a `components` field coded at intake (for example
`POWER TRAIN,FORWARD COLLISION AVOIDANCE`). It can list several components and often includes
`UNKNOWN OR OTHER` next to a specific one. The PRD asks for component classification measured against a
hand-labeled gold set; no labeler was available at build time.

## Decision

1. The canonical taxonomy is NHTSA's top-level component names (23 classes plus `OTHER`), listed in
   `config/settings.yaml`. Sub-components after `:` are dropped.
2. `component_primary` is the first specific component; `UNKNOWN OR OTHER` wins only when nothing
   specific is listed.
3. NHTSA's coded labels are ground truth for evaluation and training labels for the baseline classifier.
   They are never shown to the LLM, never embedded, and never stored in retrieval metadata for
   complaints (label leakage would inflate accuracy to near 100%).
4. Accuracy is reported two ways: exact match with the primary label, and "any-label" match (prediction
   is one of the complaint's coded components). Both are always shown; neither is reported alone.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. NHTSA taxonomy and labels (chosen) | Real labels on every row; thousands of training examples; no invented categories | Labels are coded by intake staff and can be noisy; multi-label |
| B. Custom taxonomy (for example "battery", "ADAS") | Closer to how EV teams think | Needs hand labels for everything; no ground truth |
| C. Hand-label 200 only | Matches the PRD literally | Not possible at build time; small n |

## Trade-offs accepted

NHTSA codes are noisy and coarse (`ELECTRICAL SYSTEM` covers both the 12V system and the traction
battery). Any-label accuracy is more lenient than primary accuracy; that is why both are shown.

## Consequences

The gold set can be built immediately as a silver set, then hand-verified later. Removing `UNKNOWN OR
OTHER` as primary when a specific label exists cut the `OTHER` share from 1,030 to 796 complaints.

## Revisit when

A hand-labeled gold set exists: report agreement between NHTSA codes and hand labels, and switch the
headline metric to hand labels.
