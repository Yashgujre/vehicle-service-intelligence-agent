# Model card: weekly complaint-volume forecaster

Structure follows Mitchell et al., "Model Cards for Model Reporting" (docs/research/01, section 6).
Backtest detail: [backtest-report.md](backtest-report.md). Decisions: ADR-0050 to ADR-0055.

**Status on 2026-10-19: champion registered.** Training run `train-20261019T182422Z` (MLflow parent run
`6c61abbf263f4e77b195d6d4d4d3c595`, 18:24 UTC) completed and registered `glm_poisson` as
`vsia-complaint-forecaster` version 1 with alias `champion` (nested run
`98acce0d6c244ef9a75db49e2e9a1ea5`). Numbers in this card come from that run's MLflow metrics and the
version's tags in `data/mlflow.db`, from `logs/forecast_train.log` and `logs/forecast_detect.log`, and
from the `forecasts` and `spike_alerts` tables in `data/vsia.db`. Earlier train runs that day failed while
logging a model because of skops serialization; ADR-0055 switched to cloudpickle.

## Model details

| Item | Value |
|---|---|
| Name in the registry | `vsia-complaint-forecaster` version 1, alias `champion`, status READY (MLflow `model_versions`, `registered_model_aliases`) |
| Registered run | `98acce0d6c244ef9a75db49e2e9a1ea5` (parent `6c61abbf263f4e77b195d6d4d4d3c595`), registered 2026-10-19 18:24 UTC |
| Code | `pipelines/forecast.py` (pipeline, MLflow, spike detection), `pipelines/features.py` (features, estimators, metrics, spike rule) |
| Pipeline version | `1.0` (`PIPELINE_VERSION`) |
| Type | `ComplaintForecaster`: a scikit-learn-compatible wrapper with two `HorizonModel`s, one for horizon 1 and one direct model for horizons 2 and above, each returning a point forecast and an interval |
| Eligible families | `glm_poisson` (Poisson GLM with a Poisson interval) or `gbm` (gradient boosting with Poisson loss and quantile models for the interval) |
| Champion family | `glm_poisson` (version tag `model_family`), chosen by the selection rule: validation WAPE 53.00 against 53.80 for `gbm` |
| Artifact format | cloudpickle via `mlflow.sklearn.log_model`; load only from this project's private registry (ADR-0055) |
| Training | Global model across all component series; parameters fixed at the training cut; seed 42 |
| Output | For each component and week: forecast count, lower and upper bound of a central 90% interval (`forecast.spike_interval: 0.90`) |
| Serving | `python -m pipelines.forecast detect`, or `POST /forecast/run` (weekly n8n workflow 03), loads `models:/vsia-complaint-forecaster@champion` and writes `forecasts` and `spike_alerts` |
| Owner | Forecasting workstream |
| Licence of the data | Public NHTSA complaint data |

## Intended use

- **Primary use:** give vehicle quality and service teams a weekly expected range of owner complaints per
  component for the vehicle segment in `config/settings.yaml`, and flag weeks where the count is above
  that range (spike alerts) for investigation.
- **Users:** quality analysts reading the dashboard Trends page and the n8n notification.
- **Horizon:** 1 week ahead for alerts; up to 4 weeks ahead for the planning view (`FUTURE_WEEKS = 4`).

## Out of scope

- Estimating defect rates, failure probabilities or fleet risk: complaint counts depend on fleet size,
  owner reporting behaviour and media attention, and the model has no fleet exposure data.
- Causal claims: an alert means "more complaints than expected", not "a defect exists".
- Single-vehicle or single-model forecasts: the series are aggregated over all vehicles in the segment.
- Components pooled into OTHER (ELECTRONIC STABILITY CONTROL, HYBRID PROPULSION SYSTEM,
  LATCHES/LOCKS/LINKAGES, PARKING BRAKE) are not forecast individually.

## Factors

- **Component:** 20 series with very different volumes: ELECTRICAL SYSTEM had 175 complaints in the
  12-week holdout, SEATS had 2.
- **Sparsity:** many component-weeks are zero; percentage errors are unstable for small series.
- **Level shifts and surges:** total volume rose through 2023 and surged in early 2026
  ([plot](forecast-plots/overall_weekly_volume.png)).
- **Reporting lag:** the latest complete week can still receive complaints after ingestion, so the last
  week's actual may be revised upward by the next ingestion.
- **Label source:** counts use NHTSA's coded `component_primary`, which is noisy and the first of possibly
  several components.

## Metrics

Headline: holdout 1-step WAPE, `sum abs(actual - forecast) / sum actual` over all component-weeks.
Also reported: MAE, volume-weighted MASE (scaled by the seasonal naive), sMAPE, MAPE, total-volume MAPE,
interval coverage, and WAPE relative to the 52-week seasonal naive. Selection uses mean validation 1-step
WAPE over three rolling origins (ADR-0052). Definitions are in the
[backtest report](backtest-report.md#metrics).

## Evaluation data

Rolling-origin backtest on the same 249-week panel: three 12-week validation folds starting 2025-11-10,
2026-02-02 and 2026-04-27, and a 12-week holdout from 2026-07-20 to 2026-10-05 (240 component-weeks, 649
complaints).

## Training data

| Item | Value |
|---|---|
| Source | `complaints` table in `data/vsia.db`: `date_filed` and `component_primary` only. No complaint text, no personal data |
| Corpus | 10,303 complaints filed 2022-01-02 to 2026-10-15, 8 makes, electric and hybrid SUVs and pickups, model years 2021 to 2026 |
| Panel | 249 complete Monday-start weeks, 2022-01-03 to 2026-10-05, 20 series |
| Fingerprint | `ba0e4154ef3b8c37` (SHA-256 of the weekly panel and the configuration, first 16 hex characters) |
| Training cut for the champion | `train_end_week` 2026-07-13 (version tag): all weeks before the holdout start of 2026-07-20 |

## Quantitative analyses

From completed run `train-20261019T182422Z` (parent `6c61abbf263f4e77b195d6d4d4d3c595`); full table in the
[backtest report](backtest-report.md#3-results). The values are identical to those first taken from the
failed run `b27e9d07c7f84d9da27ab31e5c279309`.

| Model | Val WAPE 1-step | Holdout WAPE 1-step | Holdout MASE | Coverage (0.90 nominal) | WAPE vs seasonal naive |
|---|---|---|---|---|---|
| glm_poisson (champion, v1) | 53.00 | 50.33 | 0.974 | 0.908 | 0.763 |
| gbm | 53.80 | 50.83 | 0.992 | 0.854 | 0.771 |
| ses (benchmark) | 50.32 | 50.43 | 0.964 | 0.921 | 0.765 |
| snaive52 (benchmark) | 69.55 | 65.95 | 1.249 | 0.721 | 1.000 |

Disaggregated by component, holdout WAPE for `glm_poisson` ranges from 20.6 (ELECTRICAL SYSTEM) to above
200 for components with 5 or fewer holdout complaints; interval coverage ranges from 0.667 (SUSPENSION) to
1.000. See the per-component table in the backtest report.

Champion version tags on `vsia-complaint-forecaster` v1: `holdout_wape_1step` 50.332,
`rel_wape_vs_snaive_1step` 0.763, `beats_seasonal_naive_1step` True, `validation_status` backtested,
`data_fingerprint` `ba0e4154ef3b8c37`. Other champion metrics on run `98acce0d6c244ef9a75db49e2e9a1ea5`:
validation MASE 1.161, holdout MAE 1.36 complaints, holdout sMAPE 58.41, total-volume MAPE 12.63, holdout
direct WAPE 51.46 (ratio to seasonal naive 0.780).

After registration, `detect` scored the 12 out-of-sample weeks after the training cut (2026-07-20 to
2026-10-05, 240 component-weeks; the same weeks as the backtest holdout, so not an independent test):

| Item | Value | Source |
|---|---|---|
| Interval coverage | 218 of 240 (0.908); 3 below the lower bound, 19 above the upper bound | `forecasts` rows with `actual` not null and `week` after 2026-07-13; `logs/forecast_detect.log` |
| Spike alerts | 18 (7.5% of component-weeks), 8 of them in the last 4 complete weeks (2026-09-14 to 2026-10-05) | `spike_alerts`; `logs/forecast_detect.log` |
| Alerts near a same-component recall | 6 of 18 against a base rate of 0.304 (pipeline definition); 4 of 18 against 0.283 with a symmetric plus or minus 28-day window | `recalls`, `spike_alerts`, `forecasts`; method in the [backtest report](backtest-report.md#do-alerts-anticipate-recalls) |
| Future forecasts | 80 rows: 20 components by 4 weeks, 2026-10-12 to 2026-11-02 | `forecasts` where `is_holdout = 0` |

Alerts are no more likely than ordinary component-weeks to sit near a recall, so they are not evidence of
early recall warning.

## Ethical considerations

- The data is public and the model sees only counts, so it carries no personal data.
- Complaint volume reflects who files complaints. Makes or models with more vocal owners or more media
  coverage will produce more alerts without being less safe. Alerts must not be read as rankings of
  manufacturers or vehicles.
- A missed spike can delay attention to a real defect cluster; a false spike costs analyst time. The
  interval width (90%) sets this trade-off and is a configuration choice, not a validated optimum.

## Caveats and recommendations

1. **Simple baselines are competitive.** SES and the 4-week moving average had lower validation WAPE than
   both registry-eligible models. The registry accepts only `glm_poisson` or `gbm` (ADR-0051), so check the
   `rel_wape_vs_snaive_1step` and `beats_seasonal_naive_1step` tags, and compare against SES in the
   backtest report before trusting the champion.
2. **About 5% of component-weeks are expected above a 90% interval by chance.** Treat a single alert as
   weak evidence; repeated alerts on one component are stronger.
3. **Retraining is skipped when the data fingerprint is unchanged** (ADR-0053). The fingerprint covers
   complete weeks only, so the weekly job retrains when a new week completes or a late-filed complaint
   changes an earlier week, and skips otherwise.
4. **The component set is fixed at training.** If pooling changes (a component crosses 30 complaints),
   `detect` refuses to run until `train --force`.
5. **Alerts do not anticipate recalls on current data.** 6 of 18 alerts were near a same-component recall
   against a base rate of 0.304 (backtest report, section 4). Present alerts as "more complaints than
   expected", not as recall predictions.
6. **The champion's fit stops at 2026-07-13.** The registered model is the one fitted for the holdout fold
   (`train_end_week` tag), so its parameters do not use the 12 most recent complete weeks, although its lag
   features read them at prediction time. Refitting on the full panel is not yet done.
7. **The artifact is a cloudpickle file,** which executes code when loaded. Load it only from this
   project's own registry (ADR-0055).
