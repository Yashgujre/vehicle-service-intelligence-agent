# Runbook: LLM provider outage or errors

## Symptom

- Chat answers in Open WebUI show "The vehicle defect assistant is unavailable right now", or n8n workflow
  04 returns 502.
- Workflow 01's "Triage Pending" step fails or times out; `triage_records` stops growing.
- `llm_calls` shows a burst of `ok = false`.

## Diagnosis

1. Error rate and messages by provider over the last hour:
   ```bash
   docker compose exec -T postgres psql -U postgres -d vsia -c \
     "select provider, model, purpose, ok, count(*), max(created_at), left(max(error), 120)
      from llm_calls where created_at > now() - interval '1 hour' group by 1,2,3,4 order by 5 desc;"
   ```
2. API configuration in use: `curl -s https://<API_FQDN>/health` (shows `llm_provider` and `llm_model`).
3. API logs (metadata only; prompts are never logged): `docker compose logs --since 1h vsia-api | grep -i -E "error|429|529|timeout"`.
4. Provider status pages (Anthropic, OpenAI).

| Finding | Likely cause |
|---|---|
| 401 / authentication errors | Key revoked, expired or mistyped in `.env` |
| 429 | Rate limit or spend limit reached on the provider account |
| 5xx / overloaded | Provider incident |
| Validation errors (`ok = false`, schema messages) | Model output drift; not an outage (see the guardrails workstream) |

## Mitigation

Switch provider without a code change (ADR-0002): edit `infra/compose/.env` on the laptop, for example
`VSIA_LLM_PROVIDER=openai` (needs `OPENAI_API_KEY`), then:

```bash
scripts/deploy_vm.sh <ip> --no-build
```

Per-request override is also possible: `POST /triage` and `POST /chat` accept `"provider": "openai"`.
For triage, pausing is often better than switching: deactivate workflow 01's schedule, let complaints
accumulate, and resume; `/triage/pending` processes the backlog newest first. Note that a provider switch
changes the tuned routing threshold (`data/models/routing_<provider>.json`); confirm it exists for the new
provider, or more items will route by the default threshold.

## Rollback

Set `VSIA_LLM_PROVIDER` back and redeploy with `--no-build`. Triage records keep their `provider` and
`model` columns, so mixed-provider periods can be filtered in evaluation.

## Escalation

If both hosted providers are down for more than a day, triage stops until one recovers (Ollama is not
run on the VM). Record the window so evaluation and dashboards exclude it.
