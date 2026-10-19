# ADR-0051: Register a global GLM or gradient-boosting model; keep per-series statistical methods as benchmarks

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** forecasting (`pipelines/features.py`: `HorizonModel`, `ComplaintForecaster`; `pipelines/forecast.py`: `CANDIDATES`, `SKLEARN_MODELS`)
- **PRD link:** FR-7, FR-8 (MLflow tracking and registry)

## Context

There are 20 short, noisy count series (ADR-0050). Per-series models fit each series alone and cannot
borrow strength from the others; most series have too few complaints for anything beyond smoothing. A
model registered in MLflow and loaded by `detect` must be a serialisable estimator with a stable
`predict` interface. FPP3 recommends comparing any method against simple benchmarks and discarding it if
it does not beat them (docs/research/01, section 12).

## Decision

Backtest seven candidates on identical folds (ADR-0052):

- **Benchmarks:** `naive` (last week), `snaive52` (same week last year), `ma4` and `ma8` (trailing means),
  `ses` (per-series simple exponential smoothing, alpha by grid search). Intervals are Poisson around the
  point forecast.
- **Registry-eligible global models**, trained on all components at once with a component identifier,
  lags 1 to 13, rolling means, same-week-last-year features, total-volume lags, horizon and week-of-year
  terms:
  - `glm_poisson`: Poisson GLM on log1p-scaled, standardised counts with a one-hot component, Poisson
    interval;
  - `gbm`: `HistGradientBoostingRegressor` with Poisson loss and the component as a categorical feature;
    interval from two quantile models.

Each eligible model is a `ComplaintForecaster`: a 1-step `HorizonModel` for horizon 1 and a direct
multi-horizon `HorizonModel` for longer horizons. Only `glm_poisson` or `gbm` can become the champion
(ADR-0053).

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Global GLM or GBM registered, statistical benchmarks scored alongside (chosen) | Shares strength across series; one artifact; scikit-learn serialisation; baselines keep it honest | A simpler benchmark can score better and still not be deployable |
| B. Per-series ETS or ARIMA (statsmodels) | Classical, interpretable | 20 fits per fold; weak on sparse series; extra dependency; harder to package as one model |
| C. Register whichever model wins, including baselines | Always deploys the best scorer | Baselines have no fitted object; `detect` would need a second code path |
| D. Deep global model (for example N-BEATS) | Strong on large panels | Overkill for 20 short series; heavy dependencies on a disk-limited laptop |

## Trade-offs accepted

On the preliminary run, SES (validation WAPE 50.32) and the 4-week moving average (50.95) beat both
eligible models (`glm_poisson` 53.00, `gbm` 53.80) on validation, while `glm_poisson` was best on the
holdout (50.33 against SES 50.43) (docs/models/backtest-report.md, preliminary). We accept registering a
global model that may tie a benchmark, because it provides calibrated intervals and a single deployable
artifact. The registered model's tags record whether it beats the seasonal naive
(`beats_seasonal_naive_1step`).

## Consequences

- The backtest report always shows benchmarks next to the champion.
- If a benchmark consistently wins, the right response is to wrap it as a `ComplaintForecaster` and make it
  eligible, not to drop the comparison.

## Revisit when

A benchmark beats the champion's validation WAPE by more than 2 points on two consecutive training runs,
or the panel grows enough (more history or finer series) for per-series models to have adequate data.
