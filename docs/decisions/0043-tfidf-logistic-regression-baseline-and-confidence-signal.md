# ADR-0043: Use a TF-IDF and logistic regression classifier as the baseline and as a confidence signal

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** evaluation and baselines (`src/vsia/classifier.py`), agent (`src/vsia/agent.py`)
- **PRD link:** FR-12 (baseline comparison), FR-6 (confidence for routing)

## Context

Two needs meet here. Evaluation needs a cheap, non-LLM baseline: if an LLM cannot beat a bag-of-words
classifier on component accuracy, it is not worth its latency and cost. Routing needs a confidence
signal independent of the LLM's self-report, which is poorly calibrated on small models (ADR-0061). The
training split has 9,803 complaints with NHTSA-coded components, enough for a classical text classifier.
The dev laptop has no GPU and other jobs share the CPU.

## Decision

Train `tfidf-logreg-v1`: word 1-2 gram and character (`char_wb`) 3-5 gram TF-IDF features in a
`FeatureUnion`, into `LogisticRegression(class_weight="balanced")`, on the **redacted complaint summary
only**, using the TRAIN split. Choose `C` from {1, 4, 16} by macro-F1 on a 15% random dev slice of TRAIN;
choose probability calibration separately (ADR-0046). When a calibrated head is used, classes with
fewer than 3 training rows are dropped (3-fold calibration needs them) and cannot be predicted. Save to `data/models/component_clf.joblib`.

Use it twice:

1. As the `heuristic` provider in the triage workflow: the same pipeline with the classifier in place of
   the LLM, reported next to the LLM providers.
2. As three confidence signals for every triage: `clf_prob_of_llm_label`, `clf_max_prob` and `agree`.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. TF-IDF word and char n-grams with logistic regression (chosen) | Seconds to minutes on CPU; probabilistic output; strong on keyword-heavy complaints; interpretable | No semantics beyond n-grams; weak on OTHER |
| B. Embedding (`nomic-embed-text`) plus logistic regression | Semantic features | Embedding 10,000 texts through Ollama competes for the CPU; adds a runtime dependency to every triage |
| C. Fine-tuned small transformer | Likely more accurate | Needs a GPU or long CPU runs; heavier artifact (disk is tight) |
| D. Keyword rules per component | Transparent | Brittle; no probabilities for routing |
| E. No baseline; LLM self-confidence only | Simplest | No reference point; uncalibrated routing |

## Trade-offs accepted

The classifier is trained on NHTSA labels (silver, ADR-0040), so `agree` partly measures agreement with
NHTSA's coding style. With a calibrated head, rare classes (fewer than 3 training rows) can never be predicted. If the model file
is missing at triage time, the three signals become 0 and every score drops; deployments must ship the
model with the routing files.

## Consequences

- Every evaluation report can be read against a baseline: measured in
  `docs/evaluation/baseline-classifier.md` (pending).
- The calibrator learns how much to trust LLM-classifier agreement per provider.
- Input is redacted text only; NHTSA's coded components are training labels, never inputs (ADR-0005).

## Revisit when

An embedding classifier beats this one by more than 5 points of any-label accuracy on gold at acceptable
CPU cost, or the calibrator's coefficients show the classifier signals carry no weight for any provider.
