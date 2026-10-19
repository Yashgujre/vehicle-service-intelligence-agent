# Evaluation report: ollama (qwen2.5:3b) on the gold split

- Generated: 2026-10-19 22:04 UTC by `python -m eval.run_eval score --provider ollama`
- Prompt version: `triage-v1`; MLflow run: `fc8e34a9260e4066ae6886f89231bfb1`
- Labels are SILVER (derived from NHTSA structured fields); see docs/data/datasheet-gold-set.md.

| Metric | Value |
|---|---|
| n | 200 |
| component_accuracy_primary | 0.405 |
| component_accuracy_any_label | 0.520 |
| component_macro_f1_primary | 0.440 |
| field_accuracy_make | 0.015 |
| field_accuracy_model | 0.015 |
| field_accuracy_model_year | 0.015 |
| severity_exact_vs_silver | 0.440 |
| severity_within_one_vs_silver | 0.925 |
| s1_precision_llm_raw | 0.444 |
| s1_recall_llm_raw | 0.160 |
| auto_route_rate | 0.275 |
| auto_route_accuracy_any_label | 0.964 |
| threshold | 0.775 |
| recall_at_5_retrieval_silver | 0.813 |
| recall_match_hit_rate_llm_silver | 0.387 |
| n_with_known_recall | 75 |
| llm_recall_match_precision_silver | 0.436 |
| llm_failure_rate | 0.010 |
| latency_median_s | 32.778 |
| latency_p95_s | 55.272 |
| cost_per_1000_usd | 0.000 |

## Any-label accuracy by true primary component

| Component | n | Accuracy |
|---|---|---|
| FORWARD COLLISION AVOIDANCE | 20 | 0.80 |
| OTHER | 20 | 0.20 |
| ELECTRICAL SYSTEM | 20 | 0.30 |
| POWER TRAIN | 20 | 0.50 |
| VEHICLE SPEED CONTROL | 17 | 0.59 |
| SERVICE BRAKES | 16 | 0.38 |
| STEERING | 16 | 0.75 |
| VISIBILITY/WIPER | 11 | 0.55 |
| SUSPENSION | 7 | 0.43 |
| STRUCTURE | 7 | 0.57 |
| AIR BAGS | 6 | 0.67 |
| ENGINE | 5 | 0.40 |
| EXTERIOR LIGHTING | 5 | 0.60 |
| LANE DEPARTURE | 4 | 0.25 |
| FUEL/PROPULSION SYSTEM | 4 | 0.25 |
| PARKING BRAKE | 3 | 1.00 |
| SEAT BELTS | 3 | 1.00 |
| SEATS | 3 | 0.67 |
| TIRES | 3 | 1.00 |
| WHEELS | 3 | 0.33 |
| LATCHES/LOCKS/LINKAGES | 3 | 0.33 |
| BACK OVER PREVENTION | 3 | 0.67 |
| HYBRID PROPULSION SYSTEM | 1 | 1.00 |
