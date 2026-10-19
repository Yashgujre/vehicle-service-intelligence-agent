# ADR-0050: Forecast weekly (Monday-start) complaint counts per component, pooling small components into OTHER

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** forecasting (`pipelines/features.py`: `weekly_counts`, `week_start`; `config/settings.yaml` `forecast`)
- **PRD link:** FR-7 (weekly volume forecast per component with spike alerts)

## Context

Quality teams want to know whether complaints about a component are rising. Daily counts for this segment
are tiny (about 6 complaints a day across all components: 10,303 complaints over 249 weeks), so daily
series are mostly zeros. Component volumes range from 3,023 complaints (ELECTRICAL SYSTEM) to 1
(ELECTRONIC STABILITY CONTROL). The most recent week is usually incomplete when the pipeline runs.

## Decision

- **Grain:** complaints per 7-day week starting Monday (`forecast.freq: W-MON`), keyed on `date_filed`,
  per NHTSA `component_primary`, as a wide zero-filled panel.
- **Complete weeks only:** drop a leading partial week and any trailing week that does not end on or
  before the latest filing date.
- **Pooling:** components with fewer than `forecast.min_weekly_total` (30) complaints **in total** are
  merged into OTHER; the pooled names are logged (`pooled_components`).
- On the current corpus this gives 249 weeks (2022-01-03 to 2026-10-05) and 20 series, with ELECTRONIC
  STABILITY CONTROL, HYBRID PROPULSION SYSTEM, LATCHES/LOCKS/LINKAGES and PARKING BRAKE pooled (MLflow
  run `b27e9d07c7f84d9da27ab31e5c279309` params).

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Weekly per component, pool under 30 total (chosen) | Counts large enough to model; matches a weekly review rhythm; one series per component users know | Pooled components get no individual forecast; OTHER mixes unrelated defects |
| B. Daily per component | Faster alerts | Mostly zeros; intervals too wide to flag anything |
| C. Weekly per make, model and component | More actionable | Thousands of near-empty series |
| D. Monthly per component | Smoother | Alerts arrive up to a month late |
| E. Keep every component, no pooling | Complete | Series with 1 to 22 complaints over 4.8 years carry no signal |

## Trade-offs accepted

Pooling depends on corpus totals, so a component that crosses 30 changes the column set; `detect` then
refuses to run until `train --force` (`pipelines/forecast.py`). The week of the latest ingestion is never
forecast against its own partial count. Counts inherit NHTSA's coding of the first-listed component.

## Consequences

- One global model can learn across 20 series (ADR-0051).
- The dashboard uses the same Monday-start weeks so charts and forecasts line up.

## Revisit when

Daily volume grows above about 50 complaints per day (daily or per-vehicle series become viable), or users
ask for alerts per make or model.
