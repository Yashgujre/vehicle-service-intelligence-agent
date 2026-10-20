# Evaluation report: gemini (gemini-3.5-flash-lite) on the gold split

- Generated: 2026-10-20 07:03 UTC by `python -m eval.run_eval score --provider gemini`
- Prompt version: `triage-v1`; MLflow run: `d18f37adecda431695cb2744c2eaac9f`
- Labels are SILVER (derived from NHTSA structured fields); see docs/data/datasheet-gold-set.md.

| Metric | Value |
|---|---|
| n | 200 |
| component_accuracy_primary | 0.535 |
| component_accuracy_any_label | 0.700 |
| component_macro_f1_primary | 0.550 |
| field_accuracy_make | 1.000 |
| field_accuracy_model | 0.995 |
| field_accuracy_model_year | 1.000 |
| severity_exact_vs_silver | 0.440 |
| severity_within_one_vs_silver | 0.895 |
| s1_precision_llm_raw | 0.455 |
| s1_recall_llm_raw | 0.800 |
| auto_route_rate | 0.440 |
| auto_route_accuracy_any_label | 0.875 |
| threshold | 0.775 |
| recall_at_5_retrieval_silver | 0.813 |
| recall_match_hit_rate_llm_silver | 0.493 |
| n_with_known_recall | 75 |
| llm_recall_match_precision_silver | 0.516 |
| llm_failure_rate | 0.000 |
| latency_median_s | 1.486 |
| latency_p95_s | 4.245 |
| cost_per_1000_usd | 0.000 |

## Any-label accuracy by true primary component

| Component | n | Accuracy |
|---|---|---|
| FORWARD COLLISION AVOIDANCE | 20 | 0.90 |
| OTHER | 20 | 0.00 |
| ELECTRICAL SYSTEM | 20 | 0.90 |
| POWER TRAIN | 20 | 0.70 |
| VEHICLE SPEED CONTROL | 17 | 0.94 |
| SERVICE BRAKES | 16 | 0.75 |
| STEERING | 16 | 0.94 |
| VISIBILITY/WIPER | 11 | 0.64 |
| SUSPENSION | 7 | 0.57 |
| STRUCTURE | 7 | 0.71 |
| AIR BAGS | 6 | 0.67 |
| ENGINE | 5 | 0.80 |
| EXTERIOR LIGHTING | 5 | 1.00 |
| LANE DEPARTURE | 4 | 0.00 |
| FUEL/PROPULSION SYSTEM | 4 | 0.25 |
| PARKING BRAKE | 3 | 0.67 |
| SEAT BELTS | 3 | 1.00 |
| SEATS | 3 | 1.00 |
| TIRES | 3 | 1.00 |
| WHEELS | 3 | 0.67 |
| LATCHES/LOCKS/LINKAGES | 3 | 0.67 |
| BACK OVER PREVENTION | 3 | 0.67 |
| HYBRID PROPULSION SYSTEM | 1 | 0.00 |
