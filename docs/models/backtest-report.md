# Backtest report: weekly complaint-volume forecaster

Rolling-origin backtest of the weekly per-component complaint forecaster in `pipelines/forecast.py` and
`pipelines/features.py`, against simple baselines. Model card: [model-card-forecaster.md](model-card-forecaster.md).
Decisions: ADR-0050 to ADR-0054.

## Status

**Preliminary. No champion is registered.** The only training run so far,
`train-20261019T054635Z` (MLflow parent run `b27e9d07c7f84d9da27ab31e5c279309`, experiment
`vsia-forecast`, 2026-10-19 05:46 UTC), completed the backtest for all seven candidates, wrote the
summary table and plots, then **failed** while logging the `glm_poisson` candidate's model (that nested
run is FAILED; its metrics and CSV artifacts were logged, its model artifact was not). Because of the
failure, the `gbm` nested run was never created, `register_champion()` never ran, and the registry has no
`vsia-complaint-forecaster` model and no `champion` alias. MLflow does not record the error message;
reproduce with `python -m pipelines.forecast train --force` and read the console output.

The numbers below come from that run's logged metrics (five FINISHED candidate runs plus the FAILED
`glm_poisson` run) and from the parent run's `summary.csv` artifact, which is the only record of the
`gbm` scores. They are real outputs of the pipeline but not of a completed, registered training. Final
champion numbers: measured in the MLflow model version description and tags of
`vsia-complaint-forecaster@champion` (pending).

## 1. Series

| Item | Value | Source |
|---|---|---|
| Unit | complaints per Monday-start week per component (`W-MON`) | `config/settings.yaml` `forecast.freq` |
| Label | NHTSA `component_primary` (reference data for counting; never a triage model input) | `complaints` table |
| Weeks | 249, 2022-01-03 to 2026-10-05 | MLflow params `n_weeks`, `first_week`, `last_week` |
| Partial weeks | Leading and trailing partial weeks dropped; the latest complaint is 2026-10-15, so the week of 2026-10-12 is excluded | `weekly_counts()` |
| Series | 20: 19 components plus OTHER | MLflow param `n_components` |
| Pooled into OTHER | ELECTRONIC STABILITY CONTROL (1 complaint), HYBRID PROPULSION SYSTEM (3), LATCHES/LOCKS/LINKAGES (22), PARKING BRAKE (10): fewer than 30 in total | MLflow param `pooled_components`; `min_weekly_total: 30`; counts from `data/vsia.db` |
| Data fingerprint | `ba0e4154ef3b8c37` | MLflow tag `data_fingerprint` |

The overall series ([plot](forecast-plots/overall_weekly_volume.png)) runs from about 10 to about 120
complaints per week (the first weeks of 2022 and early 2026 exceed 120), with a rise in level through
2023 and a surge in early 2026.

![Weekly complaint volume, all components](forecast-plots/overall_weekly_volume.png)

## 2. Backtest design

Rolling forecasting origin (FPP3 chapter 5, docs/research/01 section 12):

| Fold | Role | First target week | Weeks |
|---|---|---|---|
| 0 | validation | 2025-11-10 | 12 |
| 1 | validation | 2026-02-02 | 12 |
| 2 | validation | 2026-04-27 | 12 |
| 3 | holdout | 2026-07-20 | 12 (to 2026-10-05) |

Fold starts are read from the `fold_start` column of each candidate's `forecasts.csv` artifact.

- **Parameters are fixed at each fold start.** Models (and SES smoothing constants) are fitted only on
  targets before the fold's first week (`training_rows()` drops any row whose target is at or after the
  cut).
- **1-step mode (headline):** for each target week, the origin is the previous week, so lag features use
  actuals up to the week before. This matches weekly operation, where each Monday's forecast is made with
  last week's count.
- **Direct mode:** from the single origin before the fold, forecasts for horizons 1 to 12.
- **Seasonal features** read the same week one year before the target, which is known for horizons up to
  51.
- **Seed** 42 for every fit.

### Candidates

| Name | Kind | Point forecast | Interval |
|---|---|---|---|
| `naive` | baseline | last week's count | Poisson |
| `snaive52` | baseline | same week one year earlier | Poisson |
| `ma4`, `ma8` | baseline | mean of the last 4 or 8 weeks | Poisson |
| `ses` | per-series statistical | simple exponential smoothing per component, alpha by grid search on in-sample 1-step squared error | Poisson |
| `glm_poisson` | global ML | Poisson GLM over one-hot component, log1p-scaled lags and rolling means, seasonal lags, total-volume lags, horizon and week-of-year terms | Poisson |
| `gbm` | global ML | `HistGradientBoostingRegressor`, Poisson loss, component as a categorical feature, same features | Two quantile GBMs at 0.05 and 0.95 |

Features (MLflow param `features`): `component, h, lag1, lag2, lag3, lag4, lag8, lag13, roll4, roll8,
roll13, slag52, slag52_mean3, total_lag1, total_roll4, woy_sin, woy_cos`. GBM settings: learning rate
0.05, 300 iterations, 15 leaf nodes, minimum 20 samples per leaf, L2 1.0, no early stopping.

### Metrics

Definitions are in `pipelines/features.py`; all percentages are in percent.

| Metric | Definition |
|---|---|
| WAPE | `sum abs(y - f) / sum y` over all component-weeks. Headline (`HEADLINE = "wape"`) |
| MAE | mean absolute error per component-week, in complaints |
| MASE (volume-weighted) | per component, MAE divided by the in-sample MAE of the 52-week seasonal naive on that fold's training data (Hyndman and Koehler, 2006); averaged across components weighted by actual volume. Below 1 means better than the seasonal naive's typical in-sample error |
| sMAPE, MAPE (volume-weighted) | per component, then volume-weighted; MAPE skips zero actuals |
| Total-volume MAPE | MAPE of the weekly sum over all components |
| Coverage | share of component-weeks whose actual lies inside the interval; nominal 0.90 |
| WAPE vs seasonal naive | holdout WAPE divided by `snaive52`'s holdout WAPE; below 1 beats it |

### Selection rule

`register_champion()` picks, **among `glm_poisson` and `gbm` only**, the model with the lowest mean
validation 1-step WAPE over the three validation folds. Baselines and SES are benchmarks: they are scored
and logged but are not eligible for the registry (ADR-0051, ADR-0052).

## 3. Results (preliminary)

Holdout is fold 3 (240 component-weeks, 649 complaints). Validation columns average folds 0 to 2.

| Model | Val WAPE 1-step | Val MASE 1-step | Holdout WAPE 1-step | Holdout MAE | Holdout MASE | Holdout sMAPE | Total-volume MAPE | Coverage | WAPE vs snaive | Holdout WAPE direct | Direct vs snaive |
|---|---|---|---|---|---|---|---|---|---|---|---|
| naive | 60.31 | 1.193 | 67.95 | 1.84 | 1.355 | 71.66 | 14.49 | 0.696 | 1.030 | 62.10 | 0.942 |
| snaive52 | 69.55 | 1.502 | 65.95 | 1.78 | 1.249 | 73.95 | 20.47 | 0.721 | 1.000 | 65.95 | 1.000 |
| ma4 | 50.95 | **1.054** | 53.51 | 1.45 | 1.030 | 59.55 | 13.82 | 0.883 | 0.811 | 52.08 | 0.790 |
| ma8 | 53.02 | 1.206 | 51.56 | 1.39 | 1.012 | 59.25 | 14.32 | 0.908 | 0.782 | **49.77** | **0.755** |
| ses | **50.32** | 1.060 | 50.43 | 1.36 | **0.964** | 58.42 | **11.59** | 0.921 | 0.765 | 50.24 | 0.762 |
| glm_poisson | 53.00 | 1.161 | **50.33** | **1.36** | 0.974 | **58.41** | 12.63 | 0.908 | **0.763** | 51.46 | 0.780 |
| gbm | 53.80 | 1.162 | 50.83 | 1.37 | 0.992 | 60.23 | 17.14 | 0.854 | 0.771 | 51.12 | 0.775 |

Source: MLflow metrics `val_wape_1step`, `val_mase_1step`, `hold_*`, `rel_wape_vs_snaive_*` of the
candidate runs, and `summary.csv` in parent run `b27e9d07c7f84d9da27ab31e5c279309` (only source for
`gbm`). Bold marks the best value per column; coverage has no bold because the goal is closeness to 0.90,
not the highest value.

### Reading

1. **The champion rule would select `glm_poisson`** (validation WAPE 53.00 against 53.80 for `gbm`).
2. **Two simple methods did better on validation than both eligible models**: SES (50.32) and the 4-week
   moving average (50.95). On the holdout, `glm_poisson` (50.33) and SES (50.43) are within 0.1 points,
   with `gbm` at 50.83 and `ma8` at 51.56. With 649 complaints in the holdout, differences of about 1
   WAPE point are not evidence that one model is better.
3. **Every model except `naive` beats the seasonal naive on the holdout** (WAPE ratio below 1); the
   seasonal naive is the worst model on validation. This suggests that annual seasonality matters less in
   this series than shifts in level.
4. **Intervals:** the Poisson intervals of `glm_poisson`, `ses` and `ma8` cover 0.908 to 0.921 of
   holdout component-weeks against 0.90 nominal; the quantile-GBM interval under-covers at 0.854. Naive
   and seasonal naive intervals under-cover badly (0.696, 0.721) because their point forecasts are noisy.
5. **Total weekly volume** is forecast much better than individual components: total-volume MAPE 11.6 to
   12.6 for SES and `glm_poisson`, against component WAPE around 50. Most error comes from sparse
   components.
6. **Direct multi-step** forecasts (horizons 1 to 12 from one origin) score about the same WAPE as 1-step
   forecasts, again because weekly counts are dominated by noise rather than by short-term dynamics.

### Per-component holdout, `glm_poisson`, 1-step

From `per_component_1step.csv` of run `ce5c1a2652dc429c91df2973f1cc55ff`.

| Component | Holdout complaints | Zero weeks | WAPE | MASE | Coverage |
|---|---|---|---|---|---|
| ELECTRICAL SYSTEM | 175 | 0 | 20.6 | 0.397 | 1.000 |
| POWER TRAIN | 74 | 0 | 43.9 | 0.831 | 0.833 |
| STEERING | 68 | 0 | 44.5 | 1.048 | 0.750 |
| SUSPENSION | 61 | 1 | 61.0 | 3.588 | 0.667 |
| OTHER | 60 | 0 | 40.4 | 0.885 | 0.833 |
| FORWARD COLLISION AVOIDANCE | 45 | 2 | 51.5 | 0.525 | 0.750 |
| VEHICLE SPEED CONTROL | 28 | 3 | 80.0 | 0.818 | 0.833 |
| SERVICE BRAKES | 22 | 3 | 77.9 | 0.657 | 1.000 |
| STRUCTURE | 20 | 2 | 58.0 | 0.907 | 1.000 |
| AIR BAGS | 18 | 2 | 60.5 | 0.807 | 0.917 |
| VISIBILITY/WIPER | 15 | 5 | 80.0 | 0.484 | 0.917 |
| BACK OVER PREVENTION | 14 | 3 | 74.1 | 1.095 | 0.917 |
| EXTERIOR LIGHTING | 10 | 4 | 67.7 | 0.530 | 1.000 |
| LANE DEPARTURE | 9 | 4 | 72.0 | 0.636 | 1.000 |
| FUEL/PROPULSION SYSTEM | 7 | 9 | 158.3 | 1.275 | 0.917 |
| WHEELS | 6 | 6 | 104.3 | 1.109 | 1.000 |
| ENGINE | 5 | 10 | 206.9 | 0.638 | 0.917 |
| SEAT BELTS | 5 | 9 | 153.5 | 0.970 | 0.917 |
| TIRES | 5 | 7 | 115.2 | 1.033 | 1.000 |
| SEATS | 2 | 10 | 226.2 | 0.851 | 1.000 |

Percentage errors are not meaningful for components with fewer than about 20 complaints in 12 weeks;
read MASE and coverage for those. SUSPENSION is the clear miss: a cluster in late July and August 2026
(15 complaints in the week of 2026-08-03) that no model anticipated, which is what spike alerts are for.

![Top six components, holdout](forecast-plots/top6_components_holdout.png)

The plot shows the six highest-volume series for the 40 weeks before the holdout and the holdout itself,
with the `glm_poisson` 1-step forecast, its 90% interval, the seasonal naive and the weeks that would be
flagged as spikes.

## 4. Spike flags on the holdout

The spike rule (ADR-0054) flags a component-week when the actual is strictly above the interval upper
bound and at least 3 complaints. `detect` has not run (`spike_alerts` is empty), so there are no stored
alerts. Applying the rule to the backtest holdout predictions in the candidates' `forecasts.csv`
artifacts gives:

| Model | Component-weeks | Flags | Share |
|---|---|---|---|
| glm_poisson | 240 | 18 | 7.5% |
| ses | 240 | 14 | 5.8% |

With a central 90% interval, about 5% of component-weeks would exceed the upper bound by chance alone,
so most of these flags are expected noise rather than defect clusters. Repeated flags on one component
(SUSPENSION four times and STEERING three times under `glm_poisson`) are the stronger signal.

Alert precision (share of alerts followed or preceded by a related recall within 28 days, compared with
the base rate over all evaluated component-weeks) is computed by `detect`: measured in the `detect`
console output and `spike_alerts` (pending).

## 5. What is pending

| Item | Where it will be recorded |
|---|---|
| A completed `train` run with all seven nested runs and a logged model | MLflow experiment `vsia-forecast` |
| Champion model version, family, holdout WAPE, ratio to seasonal naive | model version description and tags (`holdout_wape_1step`, `rel_wape_vs_snaive_1step`, `beats_seasonal_naive_1step`) |
| Stored forecasts and spike alerts, interval coverage on out-of-sample weeks, alert recall-proximity rate | `forecasts`, `spike_alerts`, `detect` output |
| Update of this report's tables if the re-run changes any value | this file |

## 6. How to reproduce

```bash
source .venv/bin/activate
python -m pipelines.forecast train --force   # backtest, MLflow runs, plots, register champion
python -m pipelines.forecast detect          # forecasts + spike alerts from the champion
pytest tests/test_forecast.py                # unit tests on synthetic data
```

`train` without `--force` is skipped when the champion's `data_fingerprint` tag equals the current one
(ADR-0053). Plots are written to `docs/models/forecast-plots/` and logged to the parent run.
