# Evaluation report: heuristic (tfidf-logreg) on the gold split

- Generated: 2026-10-19 18:25 UTC by `python -m eval.run_eval score --provider heuristic`
- Prompt version: `triage-v1`; MLflow run: `64c8b60f92804a97ba6d197516ab6628`
- Labels are SILVER (derived from NHTSA structured fields); see docs/data/datasheet-gold-set.md.

| Metric | Value |
|---|---|
| n | 200 |
| component_accuracy_primary | 0.555 |
| component_accuracy_any_label | 0.680 |
| component_macro_f1_primary | 0.578 |
| field_accuracy_make | 1.000 |
| field_accuracy_model | 1.000 |
| field_accuracy_model_year | 1.000 |
| severity_exact_vs_silver | 0.645 |
| severity_within_one_vs_silver | 0.985 |
| s1_precision_llm_raw | n/a |
| s1_recall_llm_raw | 0.000 |
| auto_route_rate | 0.190 |
| auto_route_accuracy_any_label | 0.895 |
| threshold | 0.825 |
| recall_at_5_retrieval_silver | 0.813 |
| recall_match_hit_rate_llm_silver | 0.000 |
| n_with_known_recall | 75 |
| llm_recall_match_precision_silver | n/a |
| llm_failure_rate | 0.000 |
| latency_median_s | 0.081 |
| latency_p95_s | 0.181 |
| cost_per_1000_usd | 0.000 |

## Any-label accuracy by true primary component

| Component | n | Accuracy |
|---|---|---|
| FORWARD COLLISION AVOIDANCE | 20 | 0.65 |
| OTHER | 20 | 0.35 |
| ELECTRICAL SYSTEM | 20 | 0.65 |
| POWER TRAIN | 20 | 0.80 |
| VEHICLE SPEED CONTROL | 17 | 0.82 |
| SERVICE BRAKES | 16 | 0.88 |
| STEERING | 16 | 0.88 |
| VISIBILITY/WIPER | 11 | 0.73 |
| SUSPENSION | 7 | 0.29 |
| STRUCTURE | 7 | 0.71 |
| AIR BAGS | 6 | 0.83 |
| ENGINE | 5 | 0.80 |
| EXTERIOR LIGHTING | 5 | 0.80 |
| LANE DEPARTURE | 4 | 0.00 |
| FUEL/PROPULSION SYSTEM | 4 | 0.50 |
| PARKING BRAKE | 3 | 0.67 |
| SEAT BELTS | 3 | 1.00 |
| SEATS | 3 | 0.67 |
| TIRES | 3 | 0.67 |
| WHEELS | 3 | 0.67 |
| LATCHES/LOCKS/LINKAGES | 3 | 0.33 |
| BACK OVER PREVENTION | 3 | 1.00 |
| HYBRID PROPULSION SYSTEM | 1 | 0.00 |
