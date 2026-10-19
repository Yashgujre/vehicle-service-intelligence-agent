# ADR-0046: Choose the baseline classifier's probability calibration by top-label ECE on a dev slice

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** evaluation and baselines (`src/vsia/classifier.py`: `_select_config`, `_head`)
- **PRD link:** FR-6 (confidence for routing), FR-12

## Context

The baseline classifier's probabilities feed the routing score (`clf_prob_of_llm_label`, `clf_max_prob`,
ADR-0043). Class-balanced logistic regression on sparse TF-IDF features is often over- or under-confident,
and the per-provider calibrator (ADR-0061) works best when its inputs are themselves close to calibrated.
Gold and calibration rows must not be used to tune the classifier (ADR-0041).

## Decision

On a random 15% dev slice of TRAIN (seed 42), with `C` already chosen by macro-F1, fit three heads and keep
the one with the lowest **top-label expected calibration error** (10 equal-width bins), breaking ties by
log loss:

- `none`: plain `LogisticRegression`;
- `sigmoid`: `CalibratedClassifierCV(method="sigmoid", cv=3, ensemble=False)`;
- `temperature`: `CalibratedClassifierCV(method="temperature", cv=3, ensemble=False)`.

Refit the chosen configuration on all of TRAIN. `python -m vsia.classifier train --no-select` skips
selection and uses `C = 4` with temperature scaling. The choice and every candidate's dev accuracy,
macro-F1, ECE, log loss and mean confidence are written to `data/models/component_clf_metrics.json` and the
baseline report.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Select among none, sigmoid and temperature by dev ECE (chosen) | Data decides; the selection is recorded; temperature keeps the argmax unchanged | Three extra fits; dev slice reduces training data during selection only |
| B. Always sigmoid (Platt) per class | Standard | One-vs-rest sigmoid can distort multi-class probabilities |
| C. Isotonic | Flexible | Overfits with small per-class counts; many classes have under 100 rows |
| D. No calibration | Simplest | Probabilities may mislead the routing calibrator |

## Trade-offs accepted

ECE is computed on the top label only, so calibration of lower-ranked classes, which `clf_prob_of_llm_label`
uses when the LLM disagrees with the classifier, is not directly optimised. Calibrated heads need at least 3
training rows per class (3-fold), so the rarest classes are dropped from the model.

## Consequences

The calibration method in use is part of the model metadata (`meta.calibration`) and the report header;
values: measured in `docs/evaluation/baseline-classifier.md` (pending).

## Revisit when

The per-provider routing calibrator gives near-zero weight to the classifier signals, or the dev ECE of the
chosen method exceeds 0.05.
