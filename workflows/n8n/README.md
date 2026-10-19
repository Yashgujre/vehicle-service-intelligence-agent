# n8n workflows

n8n owns schedules, webhooks, retries and notifications; the Python service (`vsia.api`) owns the triage,
RAG and forecasting logic (ADR-0001). Each workflow here is a thin HTTP client of that service, except
workflow 05, the n8n-native agent variant kept for comparison and demo.

n8n Community Edition has no Git sync, so these JSON files are the version-controlled copy. After
changing a workflow in the editor, export it (Workflow menu, Download) over the file here, run the
validator, and commit.

## Workflows

| File | Trigger | What it does | PRD |
|---|---|---|---|
| `01_daily_ingest_and_triage.json` | Schedule, daily 06:00 | `POST /ingest/daily`; checks `complaints.ok` and `recalls.ok` (the API reports run errors in the body with HTTP 200); if `complaints.rows_inserted > 0`, `POST /triage/pending {"limit": 200}`; a Code node summarises counts (fetched, inserted, triaged, auto vs review). Failures go to a failure branch that notifies and then marks the execution failed | FR-1, FR-4 |
| `02_review_queue_digest.json` | Schedule, hourly; Webhook `POST /webhook/vsia-review` | Hourly: `GET /review/pending`, count the backlog, notify when it exceeds `VSIA_REVIEW_BACKLOG_THRESHOLD`. Webhook: forwards a `ReviewDecision` body to `POST /review/decision` and returns the result, so a form or reviewer UI can close the human-in-the-loop | FR-5 |
| `03_weekly_forecast_retrain.json` | Schedule, Monday 07:00 | `POST /forecast/run`; notify when the response lists spike alerts | FR-7 |
| `04_rag_chat_webhook.json` | Webhook `POST /webhook/vsia-chat` | Forwards the question to `POST /chat` and responds with `{answer, citations, refused}`; responds 502 with a fallback answer if the API fails. Called by the Open WebUI pipe | FR-9 |
| `05_triage_agent_native.json` | Webhook `POST /webhook/vsia-triage-native` | Code node redacts PII; AI Agent with Anthropic Chat Model (`claude-haiku-5-5`), Structured Output Parser (the `TriageOutput` schema) and an NHTSA recalls HTTP tool; writes to `triage_records` through the Postgres node; responds with the record | FR-4 (comparison variant) |

Every node `type` and `typeVersion` comes from the verified table in
`docs/research/02_technical_verification.md` section 2.2 (n8n 2.43.7). One exception is flagged in the
node notes and by the validator: `n8n-nodes-base.httpRequestTool` (version 4.5) is **inferred**, not read
from package source. Export one HTTP tool node from the running instance to confirm it. Parameter shapes
(for example the Schedule cron rule and the If conditions block) follow common exports but were not
checked against each node's schema; open each node once after import and save.

## Import

1. Open n8n (`https://<N8N_FQDN>`), create the owner account.
2. Create the credentials below (Credentials, Add credential). Names matter only for your reference.
3. For each file: Workflows, Add workflow, then the menu, Import from File.
4. Open every node that shows a credential warning and select the credential you created (imported files
   carry placeholder credential ids such as `REPLACE_WITH_VSIA_API_CREDENTIAL_ID`).
5. Activate workflows 01 to 04. Leave 05 inactive unless you are demonstrating it.
6. Optional: enable the disabled "Notify ..." nodes after setting `VSIA_NOTIFY_WEBHOOK_URL`.

## Credentials

| Credential type | Name used in the files | Value |
|---|---|---|
| Header Auth | `VSIA API bearer` | Name `Authorization`, value `Bearer <VSIA_API_TOKEN>` (n8n to API) |
| Header Auth | `n8n webhook bearer` | Name `Authorization`, value `Bearer <N8N_BEARER>` (callers to n8n webhooks; same value as the Open WebUI pipe valve) |
| Anthropic | `Anthropic` | Anthropic API key (workflow 05 only) |
| Postgres | `VSIA Postgres` | Host `postgres`, database `vsia`, user `vsia`, password `VSIA_DB_PASSWORD`, port 5432, SSL disabled (internal Docker network) (workflow 05 only) |

## Environment variables (set in `infra/compose/docker-compose.yml`)

| Variable | Default | Used by |
|---|---|---|
| `VSIA_API_BASE_URL` | `http://vsia-api:8000` | every API call (expressions fall back to the default if unset) |
| `VSIA_REVIEW_BACKLOG_THRESHOLD` | `25` | workflow 02 |
| `VSIA_NOTIFY_WEBHOOK_URL` | empty | disabled notification nodes (Slack, Teams or Discord style `{"text": ...}`) |
| `VSIA_CONFIDENCE_THRESHOLD` | `0.70` | workflow 05 routing |
| `N8N_BLOCK_ENV_ACCESS_IN_NODE` | `false` | required for the `$env` expressions above |
| `GENERIC_TIMEZONE` / `TZ` | `America/Chicago` | schedule times |

The API token is held in an n8n credential rather than an environment variable, so it is encrypted with
`N8N_ENCRYPTION_KEY` and not readable from expressions.

## Validate

```bash
python scripts/validate_n8n.py
```

Checks required keys, UUID node ids, unique names, verified type strings and versions, connection
integrity, unique webhook paths, Code node JavaScript syntax (when `node` is installed), and that the
Structured Output Parser schema in workflow 05 still matches `vsia.schemas.TriageOutput`. If the schema
check fails after a contract change, regenerate the schema with
`python -c "from vsia.schemas import TriageOutput; import json; print(json.dumps(TriageOutput.model_json_schema()))"`,
inline the `$defs`, and paste it into the parser node.

## Test calls (after activation)

```bash
curl -s -X POST "https://$N8N_FQDN/webhook/vsia-chat" -H "Authorization: Bearer $N8N_BEARER" \
  -H 'Content-Type: application/json' -d '{"question": "Most common complaint component for the 2022 EV6?"}'

curl -s -X POST "https://$N8N_FQDN/webhook/vsia-review" -H "Authorization: Bearer $N8N_BEARER" \
  -H 'Content-Type: application/json' -d '{"odi_number": 11770375, "accepted": true, "reviewer": "analyst"}'
```

## Known gaps

- Workflow 05's "VSIA Search Tool" calls `GET /search?q=&make=&model=&model_year=`, which runs the agent's
  vehicle-filtered recall search.
- `POST /forecast/run` trains (skipped when the data fingerprint is unchanged), then detects, and returns
  `{run_id, retrained, alerts, current_alerts}`; workflow 03 branches on `current_alerts`. HTTP 409 is
  returned only when the pipeline cannot run at all (for example an empty complaints table).
- Workflows 02 and 03 read `$env`, so `N8N_BLOCK_ENV_ACCESS_IN_NODE` is `false`. That also lets any workflow
  read the container's other variables (including `N8N_ENCRYPTION_KEY`); only trusted editors may create
  workflows on this instance (docs/security/threat-model.md).
- Workflow 05's redaction is a JavaScript subset of `vsia.guardrails.redact()` (no street addresses or
  names). Its records use `run_id` `n8n-native-<execution id>` and do not create review-queue rows.
- None of these workflows has been executed in a running n8n instance yet (ADR-0008).
