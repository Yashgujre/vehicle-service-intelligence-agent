# Service level objectives

Service level indicators (SLIs), objectives (SLOs) and error budgets for the deployed stack: the FastAPI
service, the n8n schedules, the review loop and the weekly forecast job on one OCI VM (ADR-0080). An SLI
is a measured quantity, an SLO is a target for it over a window, and the error budget is the amount of
failure the target allows (Google SRE book, docs/research/01 section 11).

Status on 2026-10-19: these are proposed targets. The stack has not run in production, so no SLI has
been measured; compliance is "not yet measured" for every row. Targets fit a single-VM portfolio system
with one maintainer, not a commercial service.

## Summary

| Area | SLI | SLO | Window | Error budget | Measurement source |
|---|---|---|---|---|---|
| API availability | Share of 5-minute probes of `GET /health` that return HTTP 200 within 5 s | 99.0% | 30 days rolling | 1% = 7.2 hours per 30 days | External probe (to add); Docker health check on `vsia-api` as a fallback signal |
| Triage latency | Share of production triage records with `latency_ms` at most 20,000, per hosted provider | 95% | 28 days rolling | 5% of triages may exceed 20 s | `triage_records.latency_ms` where `run_id` starts with `batch-` or `api-` |
| Daily triage completion | Share of days on which every complaint ingested that day has a triage record by 12:00 local time | 95% | 28 days | 1 to 2 late days per 28 | `complaints.ingested_at` vs `triage_records.created_at` |
| Ingestion freshness | Share of hourly checks at which the newest successful `complaints_api` run finished less than 26 hours ago | 97% | 28 days | about 20 failed hourly checks per 28 days | `ingestion_runs` (`kind`, `ok`, `finished_at`) |
| Review backlog age (S1) | Share of S1 review items resolved within 1 business day of `created_at` | 95% | 28 days | 1 in 20 S1 items may be late | `review_queue` joined to `triage_records.severity` |
| Review backlog age (all) | Share of review items resolved within 5 business days | 90% | 28 days | 1 in 10 items may be late | `review_queue.created_at`, `resolved_at` |
| Forecast job success | Share of scheduled Monday runs that return HTTP 200 from `POST /forecast/run` and write `forecasts` rows for the newest complete week | 11 of 12 weeks | 12 weeks rolling | 1 missed week per quarter | n8n workflow 03 execution history; `forecasts.created_at` and `week` |
| Auto-route quality | Any-label component accuracy of audited auto-routed items | at least 90% | 90 days, at least 100 audits | 10% wrong | Proposed audit labels (`labels.source = 'audit'`), see the [review workflow](../hitl/review-workflow.md#5-random-audit-sampling-recommended-not-implemented) |

## SLI definitions and queries

Queries use portable SQL (the API runs on Postgres on the VM, SQLite on the laptop). Replace the date
literal with the window start.

### API availability

- Good event: a probe gets HTTP 200 from `/health` within 5 seconds. `/health` runs `select 1` on the
  database and reads configuration; it does not call the LLM.
- Valid event: every probe in the window.
- Source: none today. Add an external probe (for example an n8n schedule on another host, or a free uptime
  service) that calls `https://<API_FQDN>/health` every 5 minutes and records the result. The Docker health
  check on the VM (`urllib.request.urlopen('http://localhost:8000/health', timeout=5)`) proves the process
  is alive, not that it is reachable through Caddy.

### Triage latency

```sql
select provider,
       count(*) as triages,
       avg(case when latency_ms <= 20000 then 1.0 else 0.0 end) as share_within_20s
from triage_records
where created_at >= '2026-10-01'
  and (run_id like 'batch-%' or run_id like 'api-%')
group by provider;
```

Evaluation runs (`eval-...`) and the n8n-native variant (`n8n-native-...`) are excluded. Ollama on the dev
laptop is excluded from the SLO: the single logged triage call took 41.5 s (`llm_calls`, 2026-10-19), and
Ollama is not deployed on the VM. The hosted-provider target is a design choice; revisit it after the
first evaluation reports `latency_p95_s` for each provider.

### Ingestion freshness

```sql
select max(finished_at) as last_ok
from ingestion_runs
where kind = 'complaints_api' and ok = true;
```

A check is good when `now - last_ok < 26 hours` (daily schedule at 06:00 plus 2 hours grace). This
measures pipeline freshness. Data freshness, the lag between an owner filing a complaint and NHTSA
publishing it, is outside the system's control and is reported separately as `max(date_filed)` on the
dashboard.

### Review backlog age

```sql
select t.severity,
       count(*) as resolved,
       avg(case when q.resolved_at <= q.created_at + interval '1 day' then 1.0 else 0.0 end) as share_within_1d
from review_queue q
join triage_records t on t.id = q.triage_record_id
where q.resolved_at >= '2026-10-01'
group by t.severity;
```

The `interval` syntax is Postgres; on SQLite use `julianday(q.resolved_at) - julianday(q.created_at) <= 1`.
Business days need a calendar; the 1-day form is a conservative proxy. Items still pending past their
target also count against the budget: include `status = 'pending' and created_at < now - target`.

### Forecast job success

Good week: workflow 03 execution succeeded and

```sql
select max(week) from forecasts where is_holdout = true;
```

equals the newest complete Monday-start week. `POST /forecast/run` returns HTTP 409 when no champion model
exists yet; that counts as a failure once a champion has been registered.

## Error budget policy

| Budget state | Action |
|---|---|
| More than 50% left | Normal changes: prompt versions, provider changes and threshold changes go through the [regression policy](../evaluation/eval-plan.md#6-regression-policy) |
| 0 to 50% left | Ship only fixes and changes that reduce risk for the affected area; write down the cause of each budget-consuming event |
| Exhausted | Freeze changes to the affected component until the window recovers; open an incident review using the [incident playbook](incident-playbook.md) |

Budget-consuming events with an external cause (NHTSA API outage, provider-wide outage) are recorded but
do not freeze changes; the [LLM provider outage runbook](runbooks/llm-provider-outage.md) and the
[ingestion runbook](runbooks/ingestion-failed.md) say how to record the window.

## Review cadence

Review SLI values monthly on the dashboard and in SQL. Tighten a target when it has been met with more
than half the budget left for three consecutive windows; loosen it only with a written reason.
