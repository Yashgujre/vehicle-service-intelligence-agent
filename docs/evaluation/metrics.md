# Evaluation metric definitions

Exact definitions of every triage metric that `eval/run_eval.py` (`score()`) computes, written so a
reader can recompute any number from the stored predictions in `data/eval/<split>_<provider>.jsonl`.
Metric names below are the keys in the `metrics` dict, the MLflow metric names (experiment
`vsia-triage-eval`) and the rows of the generated reports in `docs/evaluation/reports/`.

Plan, datasets, thresholds and regression policy: [eval-plan.md](eval-plan.md). Forecasting metrics
(WAPE, MASE, interval coverage) are defined in [the backtest report](../models/backtest-report.md).

No values appear in this file. Values are measured in `docs/evaluation/reports/<date>-<provider>-gold.md`
and `docs/evaluation/model-comparison.md`.

## Notation

For one provider and one split:

- `G` is the set of complaints that are both in the split file and in the prediction file; `n = |G|`.
- For complaint `i`: `p_i` is the predicted component (`output.component`, after the agent's taxonomy
  normalisation); `y_i` is NHTSA's `component_primary`; `A_i` is the set `components_all`, or `{y_i}`
  when that list is empty.
- `s_i` is the final severity (`output.severity`, after the S1 business rule, ADR-0062); `r_i` is the
  LLM's raw severity (`confidence_signals.llm_severity`, falling back to `s_i`); `v_i` is the silver
  severity (`severity_silver`, ADR-0044).
- `F_i` is the NHTSA incident flag: `crash or fire or injuries > 0 or deaths > 0`, read from the
  `complaints` table.
- `K_i` is `known_recalls_silver` (ADR-0045); `M_i` is the set of campaigns in `output.recall_matches`
  after citation grounding (ADR-0063); `R_i` is `confidence_signals.retrieval_ranked`, the recall-search
  tool's campaign list in rank order.
- `[x]` is 1 when `x` is true, else 0.

## Component classification

| Metric | Formula | Notes |
|---|---|---|
| `component_accuracy_primary` | `(1/n) * sum_i [p_i == y_i]` | Strict: must match NHTSA's first-listed component |
| `component_accuracy_any_label` | `(1/n) * sum_i [p_i in A_i]` | Headline. NHTSA codes many complaints with two or three components; any of them counts |
| `component_macro_f1_primary` | `sklearn.metrics.f1_score(y, p, average="macro", zero_division=0)` | Unweighted mean F1 over the **union** of classes in `y` and `p`. A class the model predicts but that never appears as a primary label in the split contributes F1 = 0 |
| `per_class_any_label_accuracy` | for each true primary class `c`: `sum_{i: y_i = c} [p_i in A_i] / count(y_i = c)` | Reported table, not an MLflow metric. Classes with 3 to 7 gold rows give anecdotal numbers |

Comparability note: `vsia.classifier` computes its own macro-F1 with `labels=sorted(set(y))` (true classes
only), so the baseline report's macro-F1 and `component_macro_f1_primary` are not computed on the same
label set. Compare the baseline and the LLM on any-label accuracy, or recompute both the same way.

## Field extraction

| Metric | Formula |
|---|---|
| `field_accuracy_make` | `(1/n) * sum_i [upper(extracted.make or "") == complaints.make]` |
| `field_accuracy_model` | `(1/n) * sum_i [extracted.model is non-empty and model_family(extracted.model) == model_family(complaints.model)]`, with `vsia.tools.model_family()` |
| `field_accuracy_model_year` | `(1/n) * sum_i [extracted.model_year == complaints.model_year]` |

Caveat: the user message sent to the LLM begins with `Vehicle on file: <year> <make> <model>`
(`agent._user_message`), and the `heuristic` provider copies these fields from the complaint record. These
metrics therefore measure faithful copying of supplied structured fields, not extraction from free text.
They catch format and normalisation errors; they are not evidence of extraction skill.

## Severity

| Metric | Formula | Notes |
|---|---|---|
| `severity_exact_vs_silver` | `(1/n) * sum_i [s_i == v_i]` | Silver severity is mostly keyword rules (ADR-0044); agreement, not accuracy |
| `severity_within_one_vs_silver` | `(1/n) * sum_i [abs(ord(s_i) - ord(v_i)) <= 1]`, with `ord(S1..S4) = 1..4` | |
| `s1_precision_llm_raw` | `TP / (TP + FP)`, `TP = sum_i [F_i and r_i == "S1"]`, `FP = sum_i [not F_i and r_i == "S1"]` | `None` when the denominator is 0 |
| `s1_recall_llm_raw` | `TP / (TP + FN)`, `FN = sum_i [F_i and r_i != "S1"]` | `None` when the denominator is 0 |

Why "LLM raw": the business rule forces `s_i = "S1"` whenever `F_i` is true, and the silver label uses the
same flags, so final-severity agreement on flagged complaints is guaranteed by construction. The raw
severity is the model's judgement from the text alone; the flags are not in the prompt. The S1 truth here
is the flag only: the three gold complaints labelled S1 by keyword rules (`S1:rule_keywords`) count as
negatives. On the gold split, `F_i` is true for 25 complaints (`data/gold/build_summary.json`), so one
missed S1 moves recall by 4 points.

## Routing

| Metric | Formula |
|---|---|
| `threshold` | `config.confidence_threshold(provider)` at scoring time |
| `auto_route_rate` | `(1/n) * sum_i [route'_i == "auto"]` |
| `auto_route_accuracy_any_label` | `sum_i [route'_i == "auto" and p_i in A_i] / sum_i [route'_i == "auto"]`; `None` when nothing is auto-routed |

`route'_i` is recomputed by `_rescore()`: the confidence is re-scored from the stored signals with the
current calibrator, and the item is routed to review when any stored hard reason exists (injection, LLM
failure) or the new confidence is below `threshold`. The stored `route` field is not used, so these metrics
always reflect the current calibrator and threshold.

## Recall linking

Only complaints with a silver known recall (`K_i` non-empty) enter the first two metrics;
`n_with_known_recall` is their count. On the gold split that is 75 complaints (`build_summary.json`).

| Metric | Formula | Notes |
|---|---|---|
| `n_with_known_recall` | `sum_i [K_i non-empty]` | |
| `recall_at_5_retrieval_silver` | `sum_{K_i non-empty} [K_i intersect R_i[:5] non-empty] / n_with_known_recall` | Measures the search tool alone. Campaigns found only through the vehicle recall lookup tool are not in `R_i` |
| `recall_match_hit_rate_llm_silver` | `sum_{K_i non-empty} [K_i intersect M_i non-empty] / n_with_known_recall` | Did the agent's final answer cite at least one known recall |
| `llm_recall_match_precision_silver` | `sum_i sum_{m in M_i} [m in candidate_recalls_i and m in K_i] / sum_i abs(M_i)` over all `i` | Share of cited campaigns that are silver known recalls. Because `K_i` is a subset of `candidate_recalls_i` by construction, this reduces to `m in K_i`. `None` when no campaign is cited |

## Reliability, latency and cost

| Metric | Formula | Notes |
|---|---|---|
| `llm_failure_rate` | `(1/n) * sum_i [confidence_signals.llm_error present]` | The schema failure rate in the plan. Counts calls where both attempts failed validation **and** transport failures after three HTTP attempts (`tenacity`, retryable status codes only). To separate them, read `llm_calls.error` (`invalid output ...` versus an exception name) |
| schema retry rate (derived) | `(1/n) * sum_i [confidence_signals.schema_retry == 1]` | Not in `score()`; computable from the stored predictions. First reply invalid, second valid |
| `latency_median_s` | `statistics.median(latency_ms) / 1000` | `latency_ms` is the agent's end-to-end time for one complaint: redaction, tools, classifier, LLM call with retries, validation; persistence excluded |
| `latency_p95_s` | `numpy.percentile(latency_ms, 95) / 1000` | Linear interpolation. With n = 200 this rests on the 10 slowest items |
| `cost_per_1000_usd` | `1000 * sum_i cost_usd_i / n` | `cost_usd_i` is the price of the successful LLM call (tokens of both attempts summed, priced from `config/settings.yaml`). It is 0 for Ollama and the heuristic provider, and 0 for failed calls even though `llm_calls` records their cost (see [cost model](../operations/cost-model.md)) |

## Baseline classifier metrics

`python -m vsia.classifier train` reports, on the same gold and calibration rows: primary and any-label
accuracy, macro-F1 and weighted-F1 over the classes present in gold, population-weighted primary accuracy
(per-class recall weighted by the corpus class share, ADR-0041), slices (S1 flags, with known recall,
multi-label, single-label), top-label expected calibration error over 10 equal-width bins, a reliability
table and a coverage curve over thresholds 0.30 to 0.90. Values: measured in
`docs/evaluation/baseline-classifier.md`.

## Statistical reading

- Gold has 200 rows. The binomial standard error of an accuracy near 0.8 is about
  `sqrt(0.8 * 0.2 / 200) = 0.028`, so differences under about 5 points between two runs are within noise
  unless tested on paired items (see the regression policy in the plan).
- Gold is capped at 20 rows per class, so plain accuracy over-weights rare classes relative to live
  traffic (ADR-0041). The calibration split is proportional to the corpus mix and is the better estimate
  of production routing behaviour.
