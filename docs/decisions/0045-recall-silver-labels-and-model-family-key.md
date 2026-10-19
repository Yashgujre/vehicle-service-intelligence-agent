# ADR-0045: Silver known-recall labels by vehicle, component and date, with a normalised model family key

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** evaluation (`eval/build_gold.py`: `model_family_key`, `match_recalls`)
- **PRD link:** FR-12; FR-4 (recall linking during triage)

## Context

The agent links complaints to recalls. Evaluating that needs, per complaint, the recalls that plausibly
cover it. NHTSA does not link complaints to recalls. Recall records carry make, model, model year,
component and report date; complaints carry the same vehicle fields, a filing date and coded components.
Model strings differ between the two sources ("MUSTANG MACH-E" versus "MUSTANG MACH E", "F-150 LIGHTNING"
versus "F-150 LIGHTNING BEV", "ID.4" versus "ID 4"), so exact matching misses true links.

## Decision

1. **Model family key:** upper-case; replace `-`, `.` and `/` with spaces; collapse spaces;
   "PLUG IN HYBRID" becomes "PHEV"; "HEV" becomes "HYBRID"; drop a trailing "BEV". Distinct vehicles stay
   distinct (ESCAPE HYBRID versus ESCAPE PHEV, IONIQ 5 versus IONIQ 5 N, RAV4 PRIME versus RAV4 PHEV).
2. **Candidate recalls:** same make, model family key and model year, with recall `report_date` on or
   before the complaint's `date_filed`. These are what an agent could legitimately know at filing time.
3. **Known recalls (silver label):** candidates whose `component_primary` is in the complaint's
   `components_all`. OTHER never matches.
4. **Later recalls, same component:** same vehicle and component but reported after filing. Stored as
   `later_recalls_same_component` for early-warning analysis; not a triage target.
5. A TF-IDF similarity between complaint text and each matched recall's summary and consequence is
   attached as a review aid only; it is not part of the label.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Vehicle, component and date rule with a family key (chosen) | Deterministic; respects what was knowable at filing; matches the agent's grounding rule (ADR-0063) | Says the recall plausibly applies, not that the owner's defect is the recalled defect |
| B. Vehicle match only | Highest recall of links | Most links would be unrelated components |
| C. Text similarity threshold | Uses defect content | Threshold arbitrary; circular with the retriever being evaluated |
| D. Hand linking | Truth | Expensive; needs domain judgement per pair |

## Trade-offs accepted

The label over-links when a vehicle has several recalls on the same component, and under-links when NHTSA
coded the complaint under a different component than the recall. On the gold split 75 of 200 complaints
have at least one known recall and 159 have at least one candidate (`data/gold/build_summary.json`);
across the corpus 4,718 complaints have a known recall.

## Consequences

- Retrieval and recall-match metrics are defined on the 75 gold complaints with known recalls
  (docs/evaluation/metrics.md); precision of cited recalls is measured against known recalls.
- The family key should match the runtime normaliser (`vsia.tools.model_family`, which prefers
  `vsia.retrieval.model_family`). **Today they diverge:** the runtime key drops parenthesised text and
  powertrain tokens, so "RAV4 PRIME", "RAV4 PLUG-IN HYBRID" and "RAV4 HYBRID" all become `RAV4`, and
  "F-150 (SUPER CREW) LIGHTNING BEV" becomes `F150LIGHTNING`; this key keeps the RAV4 variants distinct and
  keeps the parenthesised text. The agent's candidate list and the silver label can therefore disagree on
  which vehicle a recall covers. Align the two (one shared function) before reading recall metrics as
  final.

## Revisit when

Hand-linked recalls exist for gold rows (measure silver precision), NHTSA model strings change format, or
the segment adds vehicles whose names the key merges or splits incorrectly.
