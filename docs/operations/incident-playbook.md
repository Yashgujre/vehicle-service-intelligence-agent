# Incident playbook

How to run an incident on the VSIA stack: who does what, how severe it is, which levers roll a change
back, and which runbook covers the specific failure. Runbooks hold the step-by-step diagnosis; this page
does not repeat them.

| Runbook | Covers |
|---|---|
| [LLM provider outage](runbooks/llm-provider-outage.md) | Provider errors, rate limits, validation error bursts, provider switch |
| [Cost spike](runbooks/cost-spike.md) | LLM, Pinecone or OCI spend above expectation |
| [Ingestion failed](runbooks/ingestion-failed.md) | Daily NHTSA ingestion or triage workflow failures |
| [Review backlog](runbooks/review-backlog.md) | Review queue growing or ageing, routing share jumps |
| [VM out of capacity](runbooks/vm-out-of-capacity.md) | OCI host capacity, memory, disk |

## 1. Roles

Incident response follows the three Cs (coordinate, communicate, control) and three roles (Google SRE
workbook, docs/research/01 section 11). On a one-maintainer project one person may hold all three, but
should say so when the incident is declared, so the hand-off is explicit if a second person joins.

| Role | Responsibilities |
|---|---|
| Incident commander (IC) | Declares the incident and its severity, keeps the timeline, decides on rollback, declares resolution, owns the review |
| Operations lead | Diagnoses and applies mitigations and rollback levers; the only person changing the system during the incident |
| Communications lead | Updates the people who rely on the output: reviewers and the vehicle quality lead; posts start, updates and resolution |

## 2. Severity levels

| Level | Definition in this system | Examples | Response |
|---|---|---|---|
| SEV1 | Harmful or unsafe output reaches users, or data exposure | Complaint PII appears in logs, dashboard or a public snapshot; injected text causes wrong auto-routed S1 decisions; auto-routing systematically mislabels S1 complaints as low severity | Stop the harm first: route everything to review, take the dashboard read-only or to the demo snapshot. IC within 1 hour, updates every 4 hours |
| SEV2 | A core function is down or wrong at scale, no safety exposure yet | Triage stopped for more than 1 day; ingestion stale for more than 2 days; S1 review items older than 1 business day; auto-routed accuracy from audits below 80% | Same day. Mitigate with a rollback lever; updates daily |
| SEV3 | Degraded but working | Review share well above normal; spend above the daily alarm but within the monthly budget; forecast job missed one week; schema failure rate above 5% | Next business day; fix forward or roll back |
| SEV4 | Cosmetic or single-item | One wrong triage reported by a reviewer; a dashboard panel error | Track as an issue; no incident process |

Raise the level when in doubt; lowering it later costs nothing.

## 3. Process

1. **Detect.** An alert ([observability](observability.md#4-alerts)), an SLO budget burn
   ([SLOs](slos.md)), a reviewer report or a failed n8n execution.
2. **Declare.** IC records the start time, the severity, the symptoms and who holds each role.
3. **Stabilise.** Use the fastest lever from section 4 that stops further harm, even if it lowers
   throughput: sending everything to review is always acceptable.
4. **Diagnose.** Follow the matching runbook. Prefer evidence from `llm_calls`, `triage_records`
   `confidence_signals`, `ingestion_runs`, n8n execution history and MLflow over guesses.
5. **Resolve.** Fix or roll back, confirm the SLI recovered, then remove temporary levers one at a time.
6. **Record the window.** Note start and end times so evaluation and dashboards can exclude or flag the
   period; triage records keep `provider`, `model` and `prompt_version`, so affected rows are filterable.
7. **Review.** For SEV1 and SEV2, write a blameless review within 5 business days (template in section 6).

## 4. Rollback levers

Each lever is a configuration change, not a code change, unless stated. On the VM, environment changes
are made in `infra/compose/.env` on the laptop and applied with `scripts/deploy_vm.sh <ip> --no-build`.

| Lever | How | Effect | Caveats |
|---|---|---|---|
| Route everything to review | Set `VSIA_CONFIDENCE_THRESHOLD=1.01` | Every triage record goes to the queue (confidence is at most 1.0) | Applies to all providers; review load rises to 100% of volume. Value `0` is ignored by `config.confidence_threshold()` (falsy check), so it cannot be used to auto-route everything |
| Threshold override | Set `VSIA_CONFIDENCE_THRESHOLD=<value>` | Replaces the tuned per-provider threshold | Raising it sends more to review; lowering it auto-accepts more and needs evidence from evaluation (review backlog runbook) |
| Restore tuned threshold | Remove the override, or redeploy the previous `data/models/routing_<provider>.json` | Back to the evaluated threshold | Keep the previous file; `calibrate` overwrites it |
| Restore calibrator | Redeploy the previous `data/models/confidence_calibrator_<provider>.joblib` | Back to the previous score | The routing file and the calibrator must come from the same `calibrate` run; mixing them invalidates the threshold |
| Provider switch | `VSIA_LLM_PROVIDER=anthropic` or `openai` (needs the key) | All triage and chat use the other provider | Needs that provider's routing file and calibrator, otherwise fallback weights and the 0.70 default apply. Per request: `"provider"` in the `POST /triage` and `POST /chat` body |
| No-LLM degraded mode | `VSIA_LLM_PROVIDER=heuristic`, or `"provider": "heuristic"` per triage request | Triage uses the TF-IDF classifier; severity S3 unless the incident flags force S1 | Chat breaks in this mode (`complete_json` rejects non-LLM providers). Prefer per-request use for triage |
| Model change | `VSIA_LLM_MODEL=<model id>` (applies to the default provider only), or the model id in `config/settings.yaml` | Pins or reverts the model behind a provider | Settings change needs a redeploy with build; re-run evaluation before keeping a new model |
| Prompt version rollback | Revert the prompt file and `PROMPT_VERSION` in `src/vsia/agent.py` (or `vsia.rag`) and redeploy with build | Previous prompt text | Code change: prompts are files in `src/vsia/prompts/`, not registry aliases. Records keep `prompt_version` for filtering |
| Pause triage | Deactivate the schedule of n8n workflow 01 | New complaints accumulate untriaged; `/triage/pending` catches up newest first | Ingestion also pauses, because workflow 01 does both |
| Forecast champion rollback | `mlflow.MlflowClient().set_registered_model_alias("vsia-complaint-forecaster", "champion", "<previous version>")`, then `python -m pipelines.forecast detect` | `detect` and `POST /forecast/run` use the previous model | The next `train` compares the data fingerprint with the champion's tag; an older champion has a different fingerprint, so the weekly job retrains and moves the alias again. Deactivate workflow 03 until the cause is fixed. Only version 1 is registered (`glm_poisson`, `@champion`, since 2026-10-19), so there is no previous version to roll back to yet (see the [backtest report](../models/backtest-report.md)) |
| Dashboard read-only | `VSIA_READONLY=1`, or serve the demo snapshot (ADR-0072) | Stops review writes or shows static data | Use for a SEV1 that involves the dashboard |
| Stop a workflow | Deactivate the n8n workflow | Stops schedules and webhooks | Record the window |

## 5. Scenario index

| Symptom | First lever | Runbook |
|---|---|---|
| Burst of `llm_calls.ok = false` | Pause workflow 01, or switch provider | [LLM provider outage](runbooks/llm-provider-outage.md) |
| Review share jumps after a deploy | Check `confidence_method` in new records; restore routing file and calibrator | [Review backlog](runbooks/review-backlog.md) |
| Wrong auto-routed decisions reported | Route everything to review (`1.01`), then evaluate | [Evaluation plan](../evaluation/eval-plan.md#6-regression-policy) |
| Spend alarm | Provider-side limit, then pause workflow 01 | [Cost spike](runbooks/cost-spike.md) |
| No new complaints | Check `ingestion_runs` | [Ingestion failed](runbooks/ingestion-failed.md) |
| Forecast job fails or gives absurd alerts | Deactivate workflow 03; roll back the champion alias | [Backtest report](../models/backtest-report.md) |
| Containers restarting, disk full | | [VM out of capacity](runbooks/vm-out-of-capacity.md) |
| PII seen in any output or log | Dashboard read-only; stop the source; purge the affected rows and logs | Guardrails workstream (`vsia.guardrails.redact()`) |

## 6. Incident review template

```markdown
# Incident review: <title>

- Severity: SEV<n>
- Start / detected / mitigated / resolved (UTC):
- Roles: IC, operations lead, communications lead
- Affected: triage records (run_id range), review items, forecasts, users

## Summary
## Impact (with numbers from the tables, not estimates)
## Timeline
## Root cause
## What went well / what did not
## Action items (owner, due date, linked issue or ADR)
```
