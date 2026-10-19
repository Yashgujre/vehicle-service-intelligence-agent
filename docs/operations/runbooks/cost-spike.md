# Runbook: cost spike

The stack is designed to cost near zero: OCI Always Free, Pinecone Starter, Streamlit Community Cloud,
and hosted LLM calls priced per token (`config/settings.yaml`, `price_per_mtok`). Every LLM call is logged
with its cost in `llm_calls`.

## Symptom

- Provider billing alert or dashboard shows spend above the expected few dollars per month.
- Pinecone reports Starter limits approaching (read units, write units, embedding tokens; research 4.2).
- OCI shows charges (Always Free resources should show none).

## Diagnosis

1. LLM spend by day, provider and purpose:
   ```bash
   docker compose exec -T postgres psql -U postgres -d vsia -c \
     "select date(created_at) d, provider, model, purpose, count(*) calls, round(sum(cost_usd)::numeric, 4) usd
      from llm_calls where created_at > now() - interval '14 days' group by 1,2,3,4 order by 1 desc, usd desc;"
   ```
2. Who is calling: n8n executions (workflow 01 retries, workflow 04 chat volume, workflow 05 native agent
   tool loops) and Caddy access logs for `api.*` (`docker compose logs caddy | grep -c POST`).
3. Re-triage loops: the same `ref_id` (ODI number) appearing many times in `llm_calls`.
4. OCI: Billing, Cost Analysis, filter by service. A1 usage above 2 OCPU / 12 GB, block storage above
   200 GB total, or a non-free shape causes charges.

| Finding | Likely cause |
|---|---|
| `purpose = rag_answer` dominates | Chat traffic, possibly a leaked n8n webhook bearer or an exposed API token |
| One ODI number repeated | Retry loop (workflow 01 retries plus API retries) or a failing validation re-asked |
| Model differs from the configured one | `VSIA_LLM_MODEL` override pointing at a larger model |
| Pinecone embedding tokens high | Index rebuilt repeatedly |

## Mitigation

- Stop the bleed: deactivate the offending n8n workflow, or rotate `VSIA_API_TOKEN` / the n8n webhook
  bearer if a token leaked (update `.env`, the n8n credentials, the Open WebUI valve and Streamlit
  secrets, then `scripts/deploy_vm.sh <ip> --no-build`).
- Set or lower the provider's monthly spend limit in its console.
- Lower the triage batch size in workflow 01 or the retry count (`maxTries`).
- Switch to the cheapest configured model (`claude-haiku-5-5`) or pause triage.

## Rollback

Re-enable workflows and restore tokens once the cause is fixed. No data is lost by pausing; untriaged
complaints wait for the next `/triage/pending` run.

## Escalation

Any OCI charge on an Always Free design is a configuration error: stop the resource first, then
investigate. Record any deliberate paid resource in an ADR with its monthly cost.
