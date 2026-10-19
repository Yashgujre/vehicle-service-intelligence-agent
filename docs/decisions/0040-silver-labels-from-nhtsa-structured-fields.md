# ADR-0040: Derive silver evaluation labels from NHTSA structured fields

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** evaluation (`eval/build_gold.py`, `labels` table)
- **PRD link:** FR-12 (evaluation against a gold set)

## Context

Evaluating the triage agent needs labelled complaints: component, severity and the recalls that cover
each complaint. No human labeller was available when the gold set was built, and hand-labelling 500
complaints across 24 components and four severity levels is days of work for one person. NHTSA's records
already carry structured fields: the coded component list (`components_raw`), incident flags (crash,
fire, injuries, deaths), and recall campaigns with vehicle, component and report date. These fields are
never shown to the LLM (ADR-0005), so they can serve as reference labels without leaking into the
prediction.

## Decision

Build **silver** labels by deterministic rules from NHTSA structured fields: the component from NHTSA's
coded components, severity from incident flags plus keyword rules (ADR-0044), and known recalls from a
vehicle, component and date rule (ADR-0045). Mark them everywhere as silver: `label_source = "gold_silver"`
and `silver_rules_version = "silver-v1"` in `data/gold/*.jsonl`, `labels.source = 'gold_silver'` with
`reviewer = 'rules:silver-v1'`. Ship a review CSV (`data/gold/gold_set_review.csv`) and a `--promote`
command so gold rows can later be hand-verified and stored as `gold_hand`.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Silver labels from structured fields, hand review later (chosen) | Available now for all 500 rows; reproducible; zero cost; same rule for every provider | Measures agreement with NHTSA intake coding, not truth; severity rules are weak below S1 |
| B. Hand-label 200 gold rows before any evaluation | True human labels | Blocks evaluation for days; single-annotator labels without agreement checks are also noisy |
| C. LLM-generated labels with a stronger model | Fast; covers free-text judgement | Circular when evaluating LLMs; bias towards the labelling model's family; costs money |
| D. No offline evaluation, rely on the review queue | No labelling | Review labels cover only low-confidence items; no regression testing |

## Trade-offs accepted

Every metric is "agreement with NHTSA's coding", which is itself noisy and multi-label. Severity labels
below S1 come from keyword rules and are flagged `needs_hand_review = true` (175 of 200 gold rows,
`data/gold/build_summary.json`). Reports must say "silver" next to every number.

## Consequences

- `eval/run_eval.py` and `vsia.classifier` can run as soon as the corpus is loaded.
- Any-label component accuracy becomes the headline metric, because NHTSA often codes two or three
  components (76 of 200 gold rows are multi-label).
- The labels table now holds rule-derived rows; `write_labels_table()` replaces all `gold_silver` rows on
  each build, leaving `review` and `gold_hand` rows untouched.
- Hand labels and silver-versus-hand agreement are open work.

## Revisit when

At least 100 gold rows have hand labels: measure silver-versus-hand agreement per field and replace silver
severity with hand severity if agreement is below 80%; or NHTSA changes its component coding.
