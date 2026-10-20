# Baseline component classifier: results

- **Generated:** 2026-10-19T18:20:28+00:00 by `python -m vsia.classifier train` (source: `src/vsia/classifier.py`; full metrics JSON in `data/models/component_clf_metrics.json`, gitignored).
- **Model:** `tfidf-logreg-v1`: TF-IDF word 1-2 grams + char_wb 3-5 grams, LogisticRegression (C=4.0, class_weight=balanced), calibration = `none` (ADR-0043, ADR-0046).
- **Input:** redacted complaint summary only. **Train:** 9803 complaints (TRAIN split, `data/gold/splits.json`). Fit time 72.1 s; prediction 1.18 ms per complaint in a batch of 200 on the dev laptop.
- **Labels:** SILVER. Ground truth is NHTSA's coded component (`gold_silver`), not hand labels (ADR-0040). Treat every number below as agreement with NHTSA intake coding.

## Headline (GOLD, n=200, class-stratified, silver labels)

| Metric | Value |
|---|---|
| Primary-label accuracy | 55.5% |
| Any-label accuracy (prediction in components_all) | 68.0% |
| Macro-F1 (over the 23 classes present in GOLD) | 0.578 |
| Weighted-F1 | 0.552 |
| Population-weighted primary accuracy (per-class recall weighted by corpus class share) | 54.3% |

GOLD is capped at 20 per class, so plain accuracy over-weights rare classes compared with live traffic. The population-weighted figure re-weights per-class recall by the corpus class mix and is the better estimate of production accuracy (ADR-0041).

### Slices

| Slice | n | Primary accuracy | Any-label accuracy |
|---|---|---|---|
| s1_nhtsa_flags | 25 | 60.0% | 64.0% |
| with_known_recall_silver | 75 | 60.0% | 77.3% |
| multilabel | 76 | 40.8% | 73.7% |
| single_label | 124 | 64.5% | 64.5% |

### Per-class report (GOLD)

| Class | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| ELECTRICAL SYSTEM | 0.37 | 0.50 | 0.43 | 20 |
| FORWARD COLLISION AVOIDANCE | 0.46 | 0.50 | 0.48 | 20 |
| OTHER | 0.39 | 0.35 | 0.37 | 20 |
| POWER TRAIN | 0.55 | 0.55 | 0.55 | 20 |
| VEHICLE SPEED CONTROL | 0.39 | 0.29 | 0.33 | 17 |
| SERVICE BRAKES | 0.63 | 0.75 | 0.69 | 16 |
| STEERING | 0.71 | 0.75 | 0.73 | 16 |
| VISIBILITY/WIPER | 0.80 | 0.73 | 0.76 | 11 |
| STRUCTURE | 0.62 | 0.71 | 0.67 | 7 |
| SUSPENSION | 0.40 | 0.29 | 0.33 | 7 |
| AIR BAGS | 1.00 | 0.83 | 0.91 | 6 |
| ENGINE | 0.57 | 0.80 | 0.67 | 5 |
| EXTERIOR LIGHTING | 1.00 | 0.80 | 0.89 | 5 |
| FUEL/PROPULSION SYSTEM | 1.00 | 0.50 | 0.67 | 4 |
| LANE DEPARTURE | 0.00 | 0.00 | 0.00 | 4 |
| BACK OVER PREVENTION | 1.00 | 1.00 | 1.00 | 3 |
| LATCHES/LOCKS/LINKAGES | 0.00 | 0.00 | 0.00 | 3 |
| PARKING BRAKE | 1.00 | 0.67 | 0.80 | 3 |
| SEAT BELTS | 1.00 | 1.00 | 1.00 | 3 |
| SEATS | 1.00 | 0.67 | 0.80 | 3 |
| TIRES | 0.67 | 0.67 | 0.67 | 3 |
| WHEELS | 0.50 | 0.67 | 0.57 | 3 |
| HYBRID PROPULSION SYSTEM | 0.00 | 0.00 | 0.00 | 1 |

### Most frequent confusions (true -> predicted)

- VEHICLE SPEED CONTROL -> FORWARD COLLISION AVOIDANCE: 7
- ELECTRICAL SYSTEM -> OTHER: 5
- POWER TRAIN -> ELECTRICAL SYSTEM: 5
- FORWARD COLLISION AVOIDANCE -> SERVICE BRAKES: 4
- OTHER -> ELECTRICAL SYSTEM: 4
- FORWARD COLLISION AVOIDANCE -> VEHICLE SPEED CONTROL: 3
- STEERING -> SUSPENSION: 3
- LANE DEPARTURE -> ELECTRICAL SYSTEM: 3
- SERVICE BRAKES -> FORWARD COLLISION AVOIDANCE: 2
- OTHER -> POWER TRAIN: 2

## Confidence on CALIBRATION (n=300, proportional to the corpus class mix)

Overall primary accuracy 57.7%, any-label accuracy 68.0%, mean top-label confidence 0.511, top-label expected calibration error (10 bins) 0.082.

### Reliability table

| Confidence bin | n | Mean confidence | Primary accuracy | Any-label accuracy |
|---|---|---|---|---|
| 0.0-0.1 | 0 |  | n/a | n/a |
| 0.1-0.2 | 13 | 0.173 | 38.5% | 38.5% |
| 0.2-0.3 | 40 | 0.253 | 32.5% | 47.5% |
| 0.3-0.4 | 55 | 0.353 | 45.5% | 56.4% |
| 0.4-0.5 | 60 | 0.451 | 58.3% | 71.7% |
| 0.5-0.6 | 43 | 0.554 | 55.8% | 69.8% |
| 0.6-0.7 | 22 | 0.646 | 77.3% | 81.8% |
| 0.7-0.8 | 27 | 0.755 | 70.4% | 77.8% |
| 0.8-0.9 | 21 | 0.855 | 81.0% | 85.7% |
| 0.9-1.0 | 19 | 0.956 | 94.7% | 100.0% |

### Coverage and accuracy by auto-route threshold

| Threshold | Coverage (share auto-routed) | n auto | Primary accuracy | Any-label accuracy |
|---|---|---|---|---|
| 0.30 | 82.3% | 247 | 62.8% | 72.9% |
| 0.35 | 73.3% | 220 | 64.1% | 74.1% |
| 0.40 | 64.0% | 192 | 67.7% | 77.6% |
| 0.45 | 54.3% | 163 | 70.6% | 79.8% |
| 0.50 | 44.0% | 132 | 72.0% | 80.3% |
| 0.55 | 37.7% | 113 | 72.6% | 80.5% |
| 0.60 | 29.7% | 89 | 79.8% | 85.4% |
| 0.65 | 25.7% | 77 | 81.8% | 87.0% |
| 0.70 | 22.3% | 67 | 80.6% | 86.6% |
| 0.75 | 19.0% | 57 | 84.2% | 91.2% |
| 0.80 | 13.3% | 40 | 87.5% | 92.5% |
| 0.85 | 10.7% | 32 | 90.6% | 93.8% |
| 0.90 | 6.3% | 19 | 94.7% | 100.0% |

**Reading:**

- Primary accuracy first reaches 85% at threshold 0.80, where 13.3% of complaints would be auto-routed (accuracy 87.5%).
- Any-label accuracy first reaches 85% at threshold 0.60, coverage 29.7% (accuracy 85.4%).
- At the configured routing threshold (0.7, `config/settings.yaml`), this classifier alone would auto-route 22.3% with primary accuracy 80.6% and any-label accuracy 86.6%. The agent's threshold applies to its own combined confidence, not to this classifier alone.
- With n=300, each coverage cell has a binomial standard error of up to about 2.9 percentage points, and accuracy cells at high thresholds rest on fewer rows; read differences under 5 points as noise.

## Model selection (dev slice of TRAIN; GOLD and CALIBRATION untouched)

Dev slice: 1470 complaints held out from TRAIN (random 15%, seed 42); models fit on the other 8330. Rule: C by dev macro-F1; calibration by dev top-label ECE then log loss.

| C | Dev accuracy | Dev macro-F1 | Fit seconds |
|---|---|---|---|
| 1.0 | 55.2% | 0.526 | 28.5 |
| 4.0 | 57.1% | 0.531 | 43.7 |
| 16.0 | 57.0% | 0.517 | 59.8 |

| Calibration | Dev accuracy | Dev macro-F1 | Top-label ECE | Log loss | Mean confidence |
|---|---|---|---|---|---|
| none | 57.1% | 0.531 | 0.076 | 1.383 | 0.512 |
| sigmoid | 57.6% | 0.508 | 0.085 | 1.304 | 0.491 |
| temperature | 57.1% | 0.531 | 0.089 | 1.372 | 0.629 |

## Temporal check (within TRAIN)

Fit on the earliest 7842 TRAIN complaints, tested on the latest 1961 (filed on or after 2026-02-04): primary accuracy 55.2%. A random 80/20 split of the same pool gives 57.1%. The gap is the measured cost of drift for this baseline (ADR-0042). Uncalibrated LR, same C.

## Limitations

- Labels are NHTSA intake codes (silver). Intake coding is itself noisy and multi-label; the any-label metric exists because many complaints legitimately carry two or three components.
- `OTHER` (NHTSA 'UNKNOWN OR OTHER') is a catch-all with no consistent vocabulary, so it is hard for any text model.
- GOLD has 200 rows; per-class numbers for classes with 3 to 7 rows are anecdotal.
- Not yet measured: agreement with hand labels (needs the hand review in [labeling-guide.md](labeling-guide.md)).
