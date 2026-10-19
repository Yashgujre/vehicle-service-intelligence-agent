# ADR-0055: Log the forecaster with cloudpickle, not skops, and load only models this pipeline wrote

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** Forecasting (`pipelines/forecast.py`), MLflow registry
- **PRD link:** FR-7 (register the best model in MLflow)

## Context

MLflow 3.17 saves scikit-learn models with skops by default. skops refuses to load classes it has not been
told to trust. The forecaster is a custom wrapper (`pipelines.features.ComplaintForecaster`,
`HorizonModel`) around scikit-learn models; one candidate is `HistGradientBoostingRegressor`, whose internal
`TreePredictor` skops flags as unsafe by design. The first champion registration on 2026-10-19 failed for
this reason (run `b27e9d07`), so no champion existed.

## Decision

1. `mlflow.sklearn.log_model(..., serialization_format=SERIALIZATION_FORMAT_CLOUDPICKLE)`.
2. Only models written by `pipelines/forecast.py` to this project's own MLflow registry are loaded
   (`models:/vsia-complaint-forecaster@champion`); the registry is not exposed publicly (ADR-0083).

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. cloudpickle, trusted registry only (chosen) | Works for the custom wrapper and every candidate model | Loading executes code: a tampered artifact runs on load |
| B. skops with `skops_trusted_types` | Safer load | Requires trusting `TreePredictor`, which skops itself warns against; brittle across scikit-learn versions |
| C. Drop the wrapper; log plain estimators and rebuild features at load | skops-compatible for linear models | Rewrites the pipeline; gradient boosting still blocked |
| D. Custom `mlflow.pyfunc` model storing coefficients as JSON | No code on load | Only practical for the linear champion; more code |

## Trade-offs accepted

Pickle-based artifacts are a supply-chain risk (OWASP LLM03 / ML supply chain). Accepted because the
registry is private, written only by the pipeline, and backed up with the VM volume.

## Consequences

Champion `vsia-complaint-forecaster` version 1 (`glm_poisson`) was registered on 2026-10-19 after this
change.

## Revisit when

The champion is a linear model long enough to justify option D, or the registry is shared with other teams.
