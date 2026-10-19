# Model card: weekly complaint-volume forecaster

Structure follows Mitchell et al., "Model Cards for Model Reporting" (docs/research/01, section 6).
Backtest detail: [backtest-report.md](backtest-report.md). Decisions: ADR-0050 to ADR-0054.

**Status on 2026-10-19: no champion is registered.** The first training run backtested every candidate
but failed while logging a model, so the MLflow registry has no `vsia-complaint-forecaster` version and no
`champion` alias. Numbers in this card come from that run and are preliminary. Final champion numbers:
measured in the model version description and tags of `vsia-complaint-forecaster@champion` (pending).

## Model details

| Item | Value |
|---|---|
| Name in the registry | `vsia-complaint-forecaster`, alias `champion` (not yet registered) |
| Code | `pipelines/forecast.py` (pipeline, MLflow, spike detection), `pipelines/features.py` (features, estimators, metrics, spike rule) |
| Pipeline version | `1.0` (`PIPELINE_VERSION`) |
| Type | `ComplaintForecaster`: a scikit-learn-compatible wrapper with two `HorizonModel`s, one for horizon 1 and one direct model for horizons 2 and above, each returning a point forecast and an interval |
| Eligible families | `glm_poisson` (Poisson GLM with a Poisson interval) or `gbm` (gradient boosting with Poisson loss and quantile models for the interval) |
| Expected champion family | `glm_poisson`, by the selection rule applied to the preliminary run (validation WAPE 53.00 against 53.80) |
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
| Training cut for the champion | all weeks before the holdout start (2026-07-20); recorded in the `train_end_week` tag (pending) |

## Quantitative analyses (preliminary)

From run `train-20261019T054635Z` (parent `b27e9d07c7f84d9da27ab31e5c279309`); full table in the
[backtest report](backtest-report.md#3-results-preliminary).

| Model | Val WAPE 1-step | Holdout WAPE 1-step | Holdout MASE | Coverage (0.90 nominal) | WAPE vs seasonal naive |
|---|---|---|---|---|---|
| glm_poisson (expected champion) | 53.00 | 50.33 | 0.974 | 0.908 | 0.763 |
| gbm | 53.80 | 50.83 | 0.992 | 0.854 | 0.771 |
| ses (benchmark) | 50.32 | 50.43 | 0.964 | 0.921 | 0.765 |
| snaive52 (benchmark) | 69.55 | 65.95 | 1.249 | 0.721 | 1.000 |

Disaggregated by component, holdout WAPE for `glm_poisson` ranges from 20.6 (ELECTRICAL SYSTEM) to above
200 for components with 5 or fewer holdout complaints; interval coverage ranges from 0.667 (SUSPENSION) to
1.000. See the per-component table in the backtest report.

Champion values: measured in the `vsia-complaint-forecaster@champion` version tags (pending).

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
5. **No champion exists yet.** `python -m pipelines.forecast detect` exits with "no champion" until a
   training run completes. `POST /forecast/run` runs `train` before `detect`, so its first successful call
   registers a champion; if training itself fails, the API returns an error instead.
