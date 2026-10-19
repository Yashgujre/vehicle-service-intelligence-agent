# ADR-0052: Select the forecaster by mean validation WAPE over three rolling origins; report MASE and a 12-week holdout

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** forecasting (`pipelines/forecast.py`: `backtest`, `summarize`, `register_champion`; `pipelines/features.py`: metrics)
- **PRD link:** FR-7

## Context

A single train-test split on a short weekly panel gives a noisy model ranking, and selecting on the same
weeks that are reported makes the reported error optimistic. Many component-weeks are zero, so MAPE is
undefined or explosive for small series. The metric should reflect complaint volume, which is what
analysts act on.

## Decision

- **Folds:** the last 12 weeks (`forecast.holdout_weeks`) are the holdout; three earlier 12-week folds
  (`VALIDATION_FOLDS = 3`) are validation origins. On the current panel the folds start 2025-11-10,
  2026-02-02, 2026-04-27 and (holdout) 2026-07-20. Parameters are fitted only on targets before each fold
  start.
- **Modes:** 1-step-ahead forecasts within each fold (origin moves forward with actuals, parameters
  frozen) are the headline; direct forecasts for horizons 1 to 12 from the fold origin are also scored.
- **Selection metric:** mean **WAPE** (sum of absolute errors over sum of actuals, all component-weeks) of
  1-step forecasts over the three validation folds. The lowest among the eligible models (ADR-0051) is
  registered.
- **Reported:** holdout WAPE, MAE, volume-weighted MASE scaled by the in-sample seasonal-naive MAE,
  sMAPE, MAPE on non-zero weeks, total-volume MAPE and WAPE, interval coverage, and WAPE relative to the
  seasonal naive, overall and per component; all logged to MLflow.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Rolling-origin validation with WAPE, separate holdout (chosen) | Stable ranking; holdout untouched by selection; WAPE defined with zeros and weighted by volume | WAPE is dominated by large components |
| B. Select by MASE | Scale-free; standard in FPP3 | Per-component scale from seasonal naive is unstable for sparse series; volume-weighting is needed anyway |
| C. Select by MAPE or sMAPE | Familiar | Undefined or unstable with zero weeks (sMAPE above 150 on several small components in the preliminary run) |
| D. Single holdout only | Simple | One 12-week window decides; selection leaks into the reported number |
| E. Expanding window with refit at every week | Closest to operation | 4 times 12 refits per model; slow on a shared CPU |

## Trade-offs accepted

WAPE rewards accuracy on ELECTRICAL SYSTEM, POWER TRAIN and STEERING far more than on small components;
small-component behaviour is read from MASE and coverage in the per-component table. Freezing parameters
within a fold slightly understates what weekly refitting could achieve. Three folds of 12 weeks cover only
36 weeks of validation, so close scores (within about 1 WAPE point) do not separate models.

## Consequences

- Each training run produces comparable numbers for every candidate, including benchmarks, in one MLflow
  parent run.
- Selection and reporting are separate: the champion's holdout WAPE is an honest estimate of its error on
  unseen weeks.

## Revisit when

The panel has more than about 400 weeks (add folds), forecasts are used for staffing where total volume
matters more (switch to total-volume WAPE), or a probabilistic score (for example interval score) is
needed to rank interval quality.

## Update (2026-10-19)

The completed training run `train-20261019T182422Z` (MLflow parent run
`6c61abbf263f4e77b195d6d4d4d3c595`) reproduced the numbers of the preliminary run after rounding. The
selection rule chose `glm_poisson` (mean validation WAPE 53.00 against 53.80 for `gbm`), which is
registered as `vsia-complaint-forecaster` v1 `@champion` (run `98acce0d6c244ef9a75db49e2e9a1ea5`), with
holdout 1-step WAPE 50.33 against 65.95 for the seasonal naive (ratio 0.763). Source:
[backtest report](../models/backtest-report.md).
