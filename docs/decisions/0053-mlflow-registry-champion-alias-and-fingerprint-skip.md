# ADR-0053: Serve the forecaster through an MLflow registry alias and skip retraining when the data fingerprint is unchanged

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** forecasting (`pipelines/forecast.py`: `fingerprint`, `current_champion`, `register_champion`, `cmd_train`, `cmd_detect`)
- **PRD link:** FR-7, FR-8 (MLflow tracking and model registry)

## Context

The weekly n8n workflow 03 calls `POST /forecast/run`, which trains and then detects. Training seven
candidates over four folds takes CPU time on a small VM, and most runs would see the same complete weeks as
the previous run, because a week only changes when it completes or a late complaint arrives. Detection must
load "the current approved model" without code changes, and a bad model must be reversible. The MLflow
Model Registry provides versions, aliases such as `@champion`, tags and per-version descriptions
(docs/research/01, section 12); it needs a database-backed store (ADR-0081).

## Decision

- **Registry:** register the selected model as a new version of `vsia-complaint-forecaster` and point the
  alias `champion` at it. Tag the version with `data_fingerprint`, `model_family`, `run_id`,
  `train_end_week`, `holdout_wape_1step`, `rel_wape_vs_snaive_1step`, `beats_seasonal_naive_1step` and
  `validation_status = backtested`, and write a description with the selection reason and holdout scores.
- **Serving:** `detect` loads `models:/vsia-complaint-forecaster@champion` and refuses to run if no champion
  exists or the component set differs from the model's.
- **Fingerprint skip:** the fingerprint is the first 16 hex characters of SHA-256 over the weekly panel
  (CSV) and the configuration (forecast settings, pipeline version, seed, GBM parameters, candidate list,
  fold count). `train` exits early when the champion's `data_fingerprint` tag equals the current
  fingerprint, unless `--force`.
- **Rollback:** move the alias to an earlier version (docs/operations/incident-playbook.md).

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Registry alias plus fingerprint skip (chosen) | Detection code never changes; rollback is one alias move; idempotent weekly job; lineage from version to run | Requires the registry (SQLite backend); a failed training leaves no champion |
| B. Pickle file on disk, retrain every week | No MLflow dependency at serving | No lineage or rollback; wasted CPU |
| C. Registry stages (Staging, Production) | Familiar | Superseded by aliases in current MLflow documentation; fixed stage names cannot express several approved roles |
| D. Retrain on a fixed schedule regardless of data | Simple | Same results for unchanged data; noise in run history |

## Trade-offs accepted

The fingerprint does not include library versions, so a scikit-learn upgrade with unchanged data does not
trigger retraining. Moving the alias back to an older version is undone by the next weekly run if the data
fingerprint differs from that version's tag; pause workflow 03 during a rollback. As of 2026-10-19 no
version is registered: the first training run failed while logging a candidate model, before registration
(docs/models/backtest-report.md).

## Consequences

- `POST /forecast/run` is cheap on unchanged data and reports `retrained: false`.
- Every champion has a traceable parent run with plots, weekly counts and the summary table as artifacts.

## Revisit when

A second consumer needs a different approval flow (add a `challenger` alias and a promotion step), MLflow
moves to a Postgres backend, or library upgrades change predictions on unchanged data.
