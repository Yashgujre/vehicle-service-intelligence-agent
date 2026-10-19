# ADR-0041: Stratified gold set with per-class floor and cap, proportional calibration set, rest for training

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** evaluation (`eval/splits.py`, `eval/build_gold.py`)
- **PRD link:** FR-12, FR-6 (routing threshold tuned on held-out data)

## Context

The corpus is very unbalanced: ELECTRICAL SYSTEM has 3,023 of 10,303 complaints, while PARKING BRAKE has
10, HYBRID PROPULSION SYSTEM 3 and ELECTRONIC STABILITY CONTROL 1 (`data/vsia.db`). Three uses need data:
scoring (must cover rare classes and the slices that matter: S1 incidents and recall-linked complaints),
tuning the routing threshold (must look like production traffic), and training the baseline classifier
(needs most of the data). Using one set for two of these would either hide rare-class failures or bias
the threshold.

## Decision

Draw three disjoint splits with seed 42 (`splits-v1`, stored in `data/gold/splits.json`):

1. **Gold, 200 rows.** Per-class quota between a floor (`min(3, n_c // 2)`) and a cap (`min(20, n_c // 2)`),
   found by water-filling so quotas sum to 200, with largest-remainder rounding. Every class keeps at
   least half its rows for training; a class with one complaint stays out of gold. After sampling,
   within-class swaps raise the counts of S1-flag complaints to at least 20 and recall-linked complaints
   to at least 25 without changing class quotas.
2. **Calibration, 300 rows.** Proportional stratified sample of what remains, so it mirrors the corpus
   class mix. Used only to fit the confidence calibrator and choose the threshold (ADR-0061).
3. **Train.** Everything else (9,803 rows). The baseline classifier never sees gold or calibration rows.

Report gold accuracy both plain and population-weighted (per-class recall weighted by the corpus class
share), because the cap over-weights rare classes.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Capped and floored stratified gold, proportional calibration (chosen) | Rare classes visible; minimum slice sizes guaranteed; threshold tuned on a realistic mix | Gold accuracy is not a production estimate without re-weighting |
| B. Simple random 200 for gold | Unbiased production estimate | ELECTRICAL SYSTEM would take about 60 rows; many classes would have 0 or 1 row |
| C. Equal per-class gold (for example 9 each) | Balanced macro metrics | Classes with fewer than 18 complaints cannot supply it; more distortion of the mix |
| D. One shared eval set for scoring and tuning | Fewer labels needed | Threshold chosen on the scoring data inflates routing metrics |

## Trade-offs accepted

Gold plain accuracy over-weights rare classes compared with live traffic; the population-weighted figure
and the calibration-split numbers are the production estimates. Classes with 3 to 7 gold rows give
anecdotal per-class numbers. On the current build no swaps were needed (`swaps: s1 0, with_recall 0`);
gold has 25 S1-flag and 75 recall-linked rows; ELECTRONIC STABILITY CONTROL is excluded
(`data/gold/build_summary.json`).

## Consequences

- The split file is the contract: rebuilding with a different corpus re-samples every split. Freeze
  `splits.json` once reports exist and add rows by appending, not by rebuilding.
- New complaints ingested after the build belong to no split; they are production traffic.

## Revisit when

The corpus grows enough that a class crosses the cap boundaries significantly, hand labels change class
assignments, or a new split version is needed for a new segment.
