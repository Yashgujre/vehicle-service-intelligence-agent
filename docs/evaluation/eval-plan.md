# Evaluation plan: complaint triage agent

What "good enough to ship" means for the triage agent, which data it is measured on, who or what does the
measuring, and what blocks a change. Metric formulas are in [metrics.md](metrics.md). The forecaster has
its own evaluation in [the backtest report](../models/backtest-report.md).

Status on 2026-10-20: the gold, calibration and train splits are built
(`data/gold/build_summary.json`, built 2026-10-19T05:45:25Z). Three providers have been evaluated on all
200 gold rows with calibrators fitted on the calibration split: the offline classifier (`heuristic`),
local `qwen2.5:3b` (`ollama`) and `gemini-3.5-flash-lite` (`gemini`). Results are in
[model-comparison.md](model-comparison.md) and `reports/`. Cells below that still say "(pending)" refer
to providers or checks not yet run.

## 1. Objectives

The agent must, for one complaint at a time:

1. Classify the primary component into the 24-label taxonomy in `config/settings.yaml` (23 components
   plus OTHER).
2. Recognise critical (S1) complaints from the text, before the business rule adds the NHTSA flags.
3. Link the complaint to a recall that already covers the same vehicle and component, without citing
   recalls it was not shown (ADR-0063).
4. Know when it is unsure: auto-routed items must be accurate, uncertain items must go to review.
5. Return schema-valid output, fast and cheaply enough for a daily batch of up to 200 complaints
   (workflow 01, `POST /triage/pending {"limit": 200}`).

Each objective maps to metrics:

| Objective | Primary metric | Secondary metrics |
|---|---|---|
| 1 Component | `component_accuracy_any_label` | `component_accuracy_primary`, `component_macro_f1_primary`, per-class table |
| 2 Severity | `s1_recall_llm_raw` | `s1_precision_llm_raw`, `severity_within_one_vs_silver`, `severity_exact_vs_silver` |
| 3 Recall link | `recall_match_hit_rate_llm_silver` | `recall_at_5_retrieval_silver`, `llm_recall_match_precision_silver` |
| 4 Routing | `auto_route_accuracy_any_label` | `auto_route_rate` |
| 5 Operations | `llm_failure_rate` | `latency_median_s`, `latency_p95_s`, `cost_per_1000_usd` |

Field accuracy (`field_accuracy_*`) is reported but is not a ship criterion, because the vehicle fields
are supplied to the model in the prompt (see [metrics.md](metrics.md#field-extraction)).

## 2. Systems under test

| System | Provider value | Model (config/settings.yaml) | Notes |
|---|---|---|---|
| Local LLM | `ollama` | `qwen2.5:3b` | Default; zero cost; runs on the dev laptop |
| Hosted LLM A | `anthropic` | `claude-haiku-5-5` | Needs `ANTHROPIC_API_KEY` |
| Hosted LLM B | `openai` | `gpt-6-luna` | Needs `OPENAI_API_KEY` |
| No-LLM baseline | `heuristic` | `tfidf-logreg` | Same workflow, TF-IDF classifier instead of the LLM; severity always S3 before the rule |

Every run is identified by provider, model, prompt version (`triage-v1`, `agent.PROMPT_VERSION`), split
and the classifier version (`tfidf-logreg-v1`) used for the confidence signals.

## 3. Datasets

All three splits come from `eval/build_gold.py` and `eval/splits.py` (seed 42, `splits-v1`). Labels are
**silver**: derived by rules from NHTSA structured fields, not by people (ADR-0040). The dataset
description belongs in the gold-set datasheet (`docs/data/datasheet-gold-set.md`, data workstream).

| Split | Size | How drawn | Used for |
|---|---|---|---|
| Gold | 200 | Stratified by `component_primary`: per-class quota between a floor of 3 and a cap of 20 (water-filling), then swaps to reach at least 20 S1-flag and 25 known-recall complaints (ADR-0041) | Scoring only. Never used to fit or tune anything |
| Calibration | 300 | Proportional to the class mix of what remains | Fitting the confidence calibrator and choosing the threshold per provider (ADR-0061) |
| Train | 9,803 | Everything else | Training the baseline classifier |

Facts from `data/gold/build_summary.json`:

- Gold covers 23 of the 24 labels. ELECTRONIC STABILITY CONTROL is excluded (one complaint in the corpus; a class
  needs at least two); HYBRID PROPULSION SYSTEM (3 complaints) has a single gold row.
- Gold has 25 complaints with NHTSA crash, fire, injury or death flags, 75 with at least one silver known
  recall, 159 with at least one candidate recall and 76 with more than one NHTSA component.
- No swaps were needed (`swaps: s1 0, with_recall 0`): random stratified sampling already met both
  minimums.
- Splits are random, not temporal (ADR-0042). The baseline classifier report adds a within-train temporal
  check to measure the cost of that choice.

### Limits of silver labels

| Label | Rule | Limit |
|---|---|---|
| Component | NHTSA intake coding (`components_raw` mapped to the taxonomy) | Intake coding is noisy and multi-label; "correct" means agreement with NHTSA, which is why any-label accuracy is the headline. OTHER is a catch-all |
| Severity | S1 from incident flags (high precision); everything else from ordered keyword rules, default S3 (ADR-0044) | 175 of 200 gold rows are rule-based and flagged `needs_hand_review`; 76 are the default S3 with no rule fired. Severity agreement is a weak signal |
| Known recall | Same make, model family, model year; recall component in the complaint's components; recall report date on or before filing date (ADR-0045) | Says a recall plausibly covers the complaint, not that the owner's defect is the recalled defect |

Hand labels (`gold_hand`) can be added with `data/gold/gold_set_review.csv` and
`python eval/build_gold.py --promote`; none exist yet. Agreement between silver and hand labels is not yet
measured.

### Review labels

Labels written by reviewers (`labels.source = 'review'`) are a third label source. They come only from
low-confidence items, so they are biased towards hard cases and must not be mixed into the gold or
calibration splits without the process in the [review workflow](../hitl/review-workflow.md#8-feedback-loop).

## 4. Evaluator types

| Type | Used for | Status |
|---|---|---|
| Metric-based, automatic | Every metric in [metrics.md](metrics.md), against silver labels | Implemented in `eval/run_eval.py` |
| Human | Hand-labelling gold rows (review CSV), the review queue, and the proposed random audit of auto-routed items | Review queue implemented; hand labels and audit not yet done |
| LLM-as-judge | Not used for triage: every triage output is structured and has a deterministic check | Out of scope. If added for RAG chat faithfulness, calibrate the judge against at least 50 human-graded answers first and control for position and length bias (docs/research/01, section 7) |

## 5. Pass thresholds

These are proposed ship criteria for a provider and prompt version. They are design targets, not
measurements. Ratify or change them in a decision record (0040-0049 range) once the first full run
exists.

| Metric | Proposed threshold | Basis |
|---|---|---|
| `component_accuracy_any_label` (gold) | at least the baseline classifier's any-label accuracy on the same rows | An LLM that does not beat TF-IDF is not worth its cost. Baseline measured in `docs/evaluation/baseline-classifier.md`: 0.680 on gold. Gemini 0.700 passes; `qwen2.5:3b` 0.520 fails |
| `auto_route_accuracy_any_label` (gold) | at least 0.85 | Calibration target is 0.90 (ADR-0061); 5 points allowed for gold being out of sample and class-capped. Gemini 0.875 and `qwen2.5:3b` 0.964 pass |
| `auto_route_rate` (gold) | report only; must be above 0 | A threshold that auto-routes nothing has given up, not succeeded |
| `s1_recall_llm_raw` (gold) | at least 0.80 | The rule catches flagged S1s anyway; this protects unflagged critical narratives. n = 25, so 0.80 means at most 5 misses |
| `recall_match_hit_rate_llm_silver` (gold) | at least `recall_at_5_retrieval_silver` minus 0.10 | The model should not lose most of what retrieval found |
| `llm_recall_match_precision_silver` (gold) | at least 0.70 | Cited recalls should mostly be plausible |
| `llm_failure_rate` (gold) | at most 0.02 | At most 4 of 200 |
| `latency_p95_s` | hosted providers at most 20 s | 200 complaints in a daily batch must finish well within the day; Ollama on the laptop is exempt |
| `cost_per_1000_usd` | at most 2.00 USD for hosted providers | About 5 times the token-based estimate in the [cost model](../operations/cost-model.md) |

## 6. Regression policy

A change is any new prompt version, model id, provider default, retrieval setting (`retrieval.*` in
settings), taxonomy glossary, classifier version, calibrator or threshold.

1. Run the full pipeline (`all`) for the affected provider on the unchanged gold and calibration splits.
2. Compare with the last accepted report for the same provider and split.
3. **Block** the change if any primary metric in section 1 drops by more than its margin:
   - accuracy and rate metrics on all 200 rows: more than 5 points, or a paired McNemar exact test on the
     same complaints gives p below 0.05 for a drop;
   - `s1_recall_llm_raw`: any increase in missed S1 complaints of 2 or more (n = 25);
   - `llm_failure_rate`: any increase above the 0.02 threshold.
4. **Warn** (record the trade-off in the report and the PR) for drops within the margin, latency p95 up
   more than 50%, or cost per 1,000 up more than 25%.
5. Never rebuild the splits to make a comparison pass. A new split version is a new baseline; re-run every
   provider on it before comparing anything.
6. Each accepted run keeps its report in `docs/evaluation/reports/` and its MLflow run; the PR cites both.

## 7. How to run

Prerequisites: the corpus in `data/vsia.db`, the splits in `data/gold/`, the classifier model
(`python -m vsia.classifier train`), the recall index (`scripts/build_index.py`) and, for `ollama`, a
running Ollama server.

```bash
source .venv/bin/activate
python eval/build_gold.py                                   # only when (re)building splits; changes gold
python -m vsia.classifier train                             # baseline + confidence signal
python -m eval.run_eval predict   --provider ollama --split calibration
python -m eval.run_eval calibrate --provider ollama         # writes data/models/routing_ollama.json
python -m eval.run_eval predict   --provider ollama --split gold
python -m eval.run_eval score     --provider ollama         # report, MLflow, eval_runs
python -m eval.run_eval all       --provider ollama         # the four steps above
python -m eval.run_eval compare                             # docs/evaluation/model-comparison.md
```

- `predict` appends to `data/eval/<split>_<provider>.jsonl` and skips complaints already present, so an
  interrupted run resumes. `--limit N` runs a subset for smoke tests.
- Each prediction also creates a `triage_records` row with `run_id = eval-<split>-<provider>-<timestamp>`
  and never a review-queue row (ADR-0064).
- `score` writes `docs/evaluation/reports/<YYYY-MM-DD>-<provider>-<split>.md`,
  `data/eval/score_<split>_<provider>.json`, one MLflow run in experiment `vsia-triage-eval` and one
  `eval_runs` row. The dashboard's Evaluation page reads `eval_runs` and the routing files.
- Changing only the calibrator or threshold needs `calibrate` and `score`, not new LLM calls.
- Run time: the only triage call logged so far (Ollama `qwen2.5:3b` on the dev laptop, 2026-10-19) took
  41.5 seconds. At that rate 500 calls take about 6 hours; schedule local runs when the laptop is idle.

## 8. Reporting

Each report names provider, model, prompt version, split, MLflow run id and threshold, and states that
labels are silver. A run that changes a ship decision also gets an entry in the PR description with the
comparison table from `compare`.
