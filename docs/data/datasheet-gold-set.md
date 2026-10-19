# Datasheet: VSIA gold set, calibration set and train split (silver labels)

This datasheet follows Gebru et al., "Datasheets for Datasets" (2021). It covers the labelled evaluation
data built by `eval/build_gold.py` and `eval/splits.py`: a 200-complaint gold set, a 300-complaint
calibration set and the remaining 9,803-complaint train split. The parent corpus is described in
[datasheet-nhtsa-corpus.md](datasheet-nhtsa-corpus.md).

## The most important fact: these are silver labels

No human labeller was available when the set was built. Every label is derived from structured NHTSA
fields and deterministic rules, not from a person reading the complaint (ADR-0005, "Context" and
"Consequences"; ADR-0061 notes the same for the calibration split). The files and the `labels` table say
so explicitly: `label_source = gold_silver`, `silver_rules_version = silver-v1`,
`labels.reviewer = rules:silver-v1`.

Consequences for anyone reading an evaluation result:

- **Component accuracy** measures agreement with NHTSA's own component coding, not with an expert's
  judgement of the root cause.
- **Severity** labels other than the S1 flag rule come from keyword rules and are low confidence: 175 of
  the 200 gold rows are marked `needs_hand_review = true`.
- **S1 from flags is circular for final severity.** The silver S1 rule (crash, fire, injury or death flag)
  is the same business rule the triage agent applies after the LLM (ADR-0062), so final-severity agreement
  on those rows is guaranteed. The harness therefore reports S1 precision and recall on the **raw LLM
  severity** (`s1_precision_llm_raw`, `s1_recall_llm_raw` in `eval/run_eval.py`).
- **Recall matches** are a rule over vehicle, component and dates, not confirmed by reading the recall.
- The headline metric switches to hand labels once a hand-labelled set exists (ADR-0005, "Revisit when").
  The promotion path exists: `python eval/build_gold.py --promote data/gold/gold_set_review.csv` writes
  `gold_hand` rows to `labels`. No row has been promoted yet.

Code comments in `eval/build_gold.py`, `eval/splits.py` and `src/vsia/classifier.py` cite ADR-0040 to
ADR-0046 and `docs/evaluation/labeling-guide.md` for these rules; those documents do not exist. This
datasheet and ADR-0005 are the current written record.

## Motivation

**Purpose.** To measure the triage agent and the baseline classifier against fixed, reproducible labels
(FR-12), to fit the per-provider confidence calibrator and routing threshold on data disjoint from the
gold set (ADR-0061), and to train the baseline classifier on data disjoint from both.

**Creator and funding.** The project author, unfunded, from public NHTSA data.

## Composition

All counts are from `data/gold/build_summary.json` (built 2026-10-19T05:45:25Z) and `data/gold/splits.json`
(created 2026-10-19T05:45:21Z), cross-checked against the `labels` table (500 `gold_silver` rows).

| Split | Size | Sampling | Used for |
|---|---|---|---|
| gold | 200 | Stratified by `component_primary` with a per-class floor of 3 and cap of 20, plus minimums for S1 and recall coverage | Headline evaluation (`eval/run_eval.py score --split gold`) |
| calibration | 300 | Proportional stratified sample of the rest, so it mirrors the production class mix | Confidence calibrator and threshold (`eval/run_eval.py calibrate`) |
| train | 9,803 | Everything else | Baseline classifier training |
| total | 10,303 | | equals the `complaints` table at build time |

**Each record** (`gold_set.jsonl`, `calibration_set.jsonl`) holds: `odi_number`, `label_source`,
`silver_rules_version`, `make`, `model`, `model_family`, `model_year`, `date_filed`, `date_incident`,
`summary_redacted`, `components_raw`, `component_primary`, `components_all`, `flags`, `severity_silver`,
`severity_source`, `severity_rule`, `needs_hand_review`, `known_recalls_silver`, `candidate_recalls`,
`later_recalls_same_component`, `recall_rule`, `recall_text_similarity`, `split`. The train split is
stored only as ODI numbers in `splits.json`.

`gold_set_review.csv` has one header line and 200 rows for hand verification.

### Gold set (200)

Component (`component_primary`) counts:

| Component | Gold | Component | Gold |
|---|---|---|---|
| ELECTRICAL SYSTEM | 20 | EXTERIOR LIGHTING | 5 |
| FORWARD COLLISION AVOIDANCE | 20 | FUEL/PROPULSION SYSTEM | 4 |
| OTHER | 20 | LANE DEPARTURE | 4 |
| POWER TRAIN | 20 | BACK OVER PREVENTION | 3 |
| VEHICLE SPEED CONTROL | 17 | LATCHES/LOCKS/LINKAGES | 3 |
| SERVICE BRAKES | 16 | PARKING BRAKE | 3 |
| STEERING | 16 | SEAT BELTS | 3 |
| VISIBILITY/WIPER | 11 | SEATS | 3 |
| STRUCTURE | 7 | TIRES | 3 |
| SUSPENSION | 7 | WHEELS | 3 |
| AIR BAGS | 6 | HYBRID PROPULSION SYSTEM | 1 |
| ENGINE | 5 | | |

23 classes are represented. ELECTRONIC STABILITY CONTROL (1 complaint in the corpus) is excluded from the
gold set because a class needs at least 2 members (`min_class_size`); HYBRID PROPULSION SYSTEM (3 in the
corpus) gets 1, because each class keeps at least half its members outside gold.

Other gold properties:

| Property | Count |
|---|---|
| S1 by NHTSA flags | 25 (minimum required: 20) |
| With at least one silver known recall | 75 (minimum required: 25) |
| With at least one candidate recall (vehicle and date match, any component) | 159 |
| Multi-label (`components_all` has more than one component) | 76 |
| Within-class swaps needed to meet the S1 and recall minimums | 0 and 0 |

Silver severity in gold, by source rule:

| Severity | Source | Rows |
|---|---|---|
| S1 | NHTSA flags | 25 |
| S1 | keyword rule | 3 |
| S2 | keyword rules | 54 |
| S3 | keyword rules | 28 |
| S3 | default (no rule fired) | 76 |
| S4 | keyword rules | 14 |

Totals: S1 28, S2 54, S3 104, S4 14.

### Calibration set (300)

| Component | Rows | Component | Rows |
|---|---|---|---|
| ELECTRICAL SYSTEM | 89 | AIR BAGS | 6 |
| FORWARD COLLISION AVOIDANCE | 35 | ENGINE | 6 |
| POWER TRAIN | 31 | EXTERIOR LIGHTING | 6 |
| OTHER | 23 | LANE DEPARTURE | 5 |
| VEHICLE SPEED CONTROL | 19 | FUEL/PROPULSION SYSTEM | 4 |
| SERVICE BRAKES | 18 | BACK OVER PREVENTION | 3 |
| STEERING | 18 | SEAT BELTS | 3 |
| VISIBILITY/WIPER | 12 | SEATS | 2 |
| STRUCTURE | 8 | TIRES | 2 |
| SUSPENSION | 8 | WHEELS | 2 |

Silver severity: S1 flags 30, S1 keyword 4, S2 89, S3 keyword 55, S3 default 110, S4 12 (totals S1 34,
S2 89, S3 165, S4 12).

### Population reference (all 10,303 complaints)

930 complaints carry an S1 flag and 4,718 have at least one silver known recall. The gold set
over-represents both on purpose so that S1 recall and recall matching can be measured with a usable
sample.

## Collection process

The set is derived, not collected: `eval/build_gold.py` reads the `complaints` and `recalls` tables (see
the corpus datasheet for how those were collected) and applies the rules below. Build date 2026-10-19.

## Preprocessing and labelling

### Split procedure (`eval/splits.py`, version `splits-v1`)

- Strategy `random_stratified`, `temporal = false`, seed 42. Gold and calibration are random samples
  across the whole filing window (2022-01-02 to 2026-10-15), not a time-based holdout. The baseline
  classifier report adds a separate temporal check.
- Gold quotas by water-filling: each class gets a share proportional to its size, clipped between
  `min(3, n/2)` and `min(20, n/2)`, with the total fixed at 200.
- After sampling, within-class swaps can raise the number of S1 and recall-bearing complaints to the
  minimums (20 and 25); none were needed.
- Calibration: proportional stratified sample of the remaining complaints.

### Component label

`component_primary` as defined in ADR-0005: the first specific canonical component in NHTSA's
`components_raw`, `OTHER` only when nothing specific is listed. `components_all` keeps every canonical
component; the harness counts a prediction correct "any-label" if it is in `components_all`.

### Severity rubric (`silver-v1`)

Order of precedence: S1 from NHTSA flags, then keyword rules S1, S2, S3, S4, then default S3.

| Severity | Rule ids | Trigger (summary) |
|---|---|---|
| S1 | `flags:crash`, `fire`, `injuries`, `deaths` | NHTSA crash or fire flag, or injuries or deaths above zero. High precision, `needs_hand_review = false` |
| S1 | `s1_total_loss` | Complete loss of power, braking or steering, only when the text also describes a moving vehicle |
| S2 | `s2_phantom_or_sudden_braking`, `s2_unintended_acceleration`, `s2_loss_of_power`, `s2_steering_or_adas`, `s2_brake_warning_or_restraints` | Phantom or sudden braking, unintended acceleration, loss or reduction of power, steering or driver-assistance jerks, brake, airbag, seat belt or wiper failures |
| S3 | `s3_charging_or_battery`, `s3_no_start_or_shift`, `s3_camera_display_hvac`, `s3_doors_lights`, `s3_mechanical_or_recall_remedy` | Charging and 12 V battery, no start, camera, display, HVAC, leaks, doors, lights, key fob, vibration, glass, parts availability |
| S4 | `s4_comfort_cosmetic_infotainment` | Noise, trim, paint, audio, phone and navigation |
| S3 | `default_s3` | No rule fired |

Every rule other than the flag rule sets `needs_hand_review = true`.

### Recall labels

| Field | Rule |
|---|---|
| `candidate_recalls` | Recalls for the same make, model family key and model year with `report_date` on or before `date_filed` |
| `known_recalls_silver` | Candidates whose `component_primary` is in the complaint's `components_all` (`OTHER` never matches) |
| `later_recalls_same_component` | Same vehicle and component, reported after the complaint was filed (useful for early-warning analysis, not a triage target) |
| `recall_text_similarity` | TF-IDF similarity between the complaint and recall text, for reviewer context only |

The model family key (`eval/build_gold.py` `model_family_key`) upper-cases, turns `-`, `.` and `/` into
spaces, maps `PLUG-IN HYBRID` to `PHEV` and `HEV` to `HYBRID`, drops a trailing `BEV`, and keeps distinct
vehicles distinct (for example RAV4 PRIME and RAV4 PHEV). This differs from the retrieval-side
normalisation `vsia.retrieval.model_family`, which folds RAV4 variants together; the triage agent can
therefore see candidate recalls that the silver rule does not count, and the reverse.

### Redaction and leakage

`summary_redacted` is the narrative after `vsia.guardrails.redact()`. Raw narratives are not written to
`data/gold/`. `components_raw`, `component_primary` and `components_all` are labels: the harness loads the
complaint from the database and triages it without them (ADR-0005).

## Uses

**Intended:**
- Gold: headline triage metrics for every provider (component accuracy, macro-F1, field accuracy,
  severity agreement, raw-LLM S1 precision and recall, auto-route rate and accuracy, retrieval recall@5,
  recall match hit rate, failure rate, latency, cost per 1,000; `eval/run_eval.py`).
- Calibration: fitting `confidence_calibrator_<provider>.joblib` and choosing the lowest threshold whose
  auto-routed accuracy reaches the 0.90 target, written to `routing_<provider>.json` (ADR-0061).
- Train: the TF-IDF baseline classifier.

**Results.** Triage agent results: measured in docs/evaluation/ (pending); no triage evaluation has been
run on this database (`eval_runs` is empty, `data/eval/` does not exist, and no calibrator or routing file
is in `data/models/`). The baseline classifier, trained on the train split and scored on gold, is reported
in [docs/evaluation/baseline-classifier.md](../evaluation/baseline-classifier.md) (generated
2026-10-19T18:20:28Z); read those numbers as agreement with silver labels.

**Not intended:**
- Claiming expert-level accuracy. Agreement with silver labels is agreement with NHTSA coding and keyword
  rules.
- Tuning prompts or thresholds on the gold split. Calibration is the tuning split; gold stays untouched
  (ADR-0061).
- Measuring generalisation to future complaints. The split is random, not temporal.
- Per-class conclusions for classes with 3 or fewer gold rows.

**Known risks.** Keyword severity rules favour vocabulary common in EV complaints; 76 of 200 gold rows
fall through to the default S3. ELECTRICAL SYSTEM is capped at 20 in gold (10% of gold, 29.3% of the
corpus), so gold-set accuracy is not the production-mix accuracy; the calibration set is the
production-mix sample.

## Distribution

The gold files contain only redacted narratives and are not git-ignored (`data/gold/` is outside the
ignore list), so they can be published with the repository. They inherit the source terms of the NHTSA
data.

## Maintenance

- **Rebuild:** `python eval/build_gold.py` rewrites the splits, files and all `gold_silver` rows in
  `labels` (earlier silver rows are deleted first). Because the split is seeded and stratified on the
  current corpus, adding complaints changes the split; rebuilds must bump the version and re-run every
  evaluation.
- **Hand labels:** edit `gold_set_review.csv`, then `--promote` to write `gold_hand` rows.
- **Review labels:** analyst decisions from the review queue go to `labels` with `source = review`
  ([review workflow](../hitl/review-workflow.md)); they are the planned input for refitting the calibrator
  (ADR-0061).
- **Versioning:** `splits-v1` and `silver-v1` are recorded in every file. Any rule change must change the
  version string.
