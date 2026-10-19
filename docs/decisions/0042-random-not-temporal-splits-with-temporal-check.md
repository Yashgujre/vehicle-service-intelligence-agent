# ADR-0042: Draw gold and calibration splits at random across the filing window, and measure drift separately

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** evaluation (`eval/splits.py`, `src/vsia/classifier.py`)
- **PRD link:** FR-12

## Context

Complaints span 2022-01-02 to 2026-10-15. In production the agent triages new complaints, so a
time-based split (train on the past, test on the most recent period) would best imitate deployment for
any model trained on the corpus. But the evaluation has competing needs: the gold set must reach class
floors and slice minimums (ADR-0041), and rare classes do not appear in every period. The LLM itself is
not trained on the corpus; only the TF-IDF baseline classifier and the confidence calibrator are.

## Decision

Draw gold and calibration as random stratified samples across the whole filing window
(`splits.json` meta: `strategy = "random_stratified"`, `temporal = false`). Quantify the cost of that
choice for the one corpus-trained model with a **temporal check inside TRAIN** in
`vsia.classifier._temporal_check()`: fit on the earliest 80% of TRAIN by filing date, test on the latest
20%, and compare with a random 80/20 split of the same rows using the same settings. Report both numbers
in the baseline classifier report.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Random stratified splits plus a within-train temporal check (chosen) | Meets class floors and slice minimums; drift still measured | Gold numbers can be optimistic for the classifier if vocabulary drifts |
| B. Temporal gold (latest weeks) | Mirrors deployment | Rare classes and S1 or recall slices may be missing from a short recent window |
| C. Temporal and stratified (stratify within the latest N months) | Closer to deployment with coverage | Needs a long recent window to reach floors; leaves less recent data for training |
| D. Rolling temporal evaluation of the LLM | Best production estimate | Many more LLM calls; no stable benchmark for regression tests |

## Trade-offs accepted

The TF-IDF classifier sees training complaints filed after some gold complaints, so its gold accuracy may
overstate its accuracy on future complaints. The calibrator is fitted on a random sample, so its
calibration on future traffic needs the production audit (docs/hitl/review-workflow.md section 5). The
temporal-versus-random gap is the measured drift cost: measured in `docs/evaluation/baseline-classifier.md`
(pending).

## Consequences

- Gold is a stable benchmark for regression tests across prompt and provider changes.
- Forecasting uses a separate, strictly temporal rolling-origin backtest (ADR-0052); this decision does
  not apply to it.

## Revisit when

The temporal check shows a gap of more than 5 accuracy points between temporal and random splits, or the
production audit's auto-route accuracy falls more than 5 points below the gold-split value.
