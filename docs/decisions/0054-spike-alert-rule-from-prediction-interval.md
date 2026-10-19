# ADR-0054: Flag a spike when the weekly count exceeds the 90% interval upper bound and is at least 3

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** forecasting (`pipelines/features.py`: `flag_spikes`; `pipelines/forecast.py`: `cmd_detect`)
- **PRD link:** FR-7 (spike alerts)

## Context

Analysts need to know when a component's complaints rise above what is normal for it. A fixed count
threshold ignores scale: in the 12-week holdout ending 2026-10-05, ELECTRICAL SYSTEM had 175 complaints
and SEATS had 2 (docs/models/backtest-report.md).
Small series produce large relative jumps from tiny counts (1 to 2 complaints). There are no labelled
"true spikes" to tune a detector against.

## Decision

For each component and evaluated week, using the champion's 1-step forecast and its central interval at
`forecast.spike_interval` (0.90):

- **Flag** when `actual > upper` and `actual >= 3` (`MIN_ALERT_COUNT`).
- **Ratio** reported with each alert: `actual / max(upper, 1)`, so a near-zero bound does not explode it.
- **Current** alerts are those in the last 4 complete weeks (`RECENT_WEEKS`); older ones stay as history.
- **Context check:** each alert lists recall campaigns for the same component reported within 28 days
  before the week starts or after it ends (`RECALL_WINDOW_DAYS`), and `detect` prints the share of alerts
  with a nearby recall against the base rate over all evaluated component-weeks. This is a weak external
  validity check, not a label.
- Alerts are written to `spike_alerts`; `POST /forecast/run` returns them so n8n can notify.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Prediction-interval exceedance with a minimum count (chosen) | Adapts to each component's level and noise; same model as the forecast; interpretable ("above the expected range") | About 5% of weeks exceed a 90% bound by chance; interval quality drives alert quality |
| B. Fixed z-score on a rolling mean | Simple | Gaussian assumption wrong for small counts |
| C. Week-over-week percentage change | Easy to explain | Explodes on small counts; ignores seasonality |
| D. Change-point detection (CUSUM, Bayesian) | Detects sustained shifts | Extra method to tune; no labels to tune against |
| E. Higher interval (99%) | Fewer false alarms | Misses moderate clusters; quantile models at 0.005 are unstable with this data |

## Trade-offs accepted

With a 90% central interval, roughly 1 in 20 component-weeks is expected above the bound with no real
change. Applied to the preliminary backtest holdout, the rule gives 18 flags in 240 component-weeks for
`glm_poisson` and 14 for SES (docs/models/backtest-report.md), so most single alerts are noise; repeated
alerts on one component carry the signal. Poisson intervals assume variance equals the mean and
under-cover overdispersed series; the GBM quantile interval covered 0.854 on the preliminary holdout.

## Consequences

- Alert volume can be tuned with two settings (`spike_interval`, `MIN_ALERT_COUNT`) without retraining
  the point model, except that GBM interval models are refitted for a new interval level.
- Alert precision against recalls is measured by `detect` (pending, no `detect` run yet). See the update
  below for the first result.

## Revisit when

Analysts label at least 30 alerts as useful or not (tune the interval and minimum count on those labels),
the recall-proximity rate of alerts is not above the base rate after 12 weekly runs, or alert volume
exceeds what one analyst reviews in a week.

## Update (2026-10-19)

The completed training run `train-20261019T182422Z` registered `glm_poisson` as
`vsia-complaint-forecaster` v1 `@champion` (run `98acce0d6c244ef9a75db49e2e9a1ea5`), and `detect` ran
with it on the 12 weeks after the training cut (2026-07-20 to 2026-10-05, 240 component-weeks). It stored
18 spike alerts, the same 18 flags as the backtest holdout above; SES gives 14 on the same weeks. The
interval covered 218 of 240 component-weeks (0.908), with 19 above the upper bound and 3 below.

The recall-proximity check is no longer pending. Under the pipeline definition (`near_recall()` in
`pipelines/forecast.py`), 6 of 18 alerts (0.333) had a same-component recall nearby, against a base rate of
0.304 over all 240 component-weeks. Under a stricter symmetric plus or minus 28-day window, 4 of 18 (0.222)
did, against a base rate of 0.283. Alerts are therefore not early warnings of recalls on this data; they
remain "more complaints than expected" signals for an analyst. With 18 alerts the check has little power.
This is one run, not the 12 weekly runs named in the revisit trigger. Source:
[backtest report](../models/backtest-report.md), section 4.
