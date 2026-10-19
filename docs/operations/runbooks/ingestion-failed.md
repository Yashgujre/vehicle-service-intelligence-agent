# Runbook: daily ingestion failed

Applies to the OCI VM stack. Commands run in `/opt/vsia/infra/compose` on the VM unless noted.

## Symptom

- n8n workflow "VSIA 01 Daily ingest and triage" shows a failed execution (the "Mark Execution Failed"
  node threw), or the failure notification arrived.
- The dashboard shows no complaints filed in the last two or more days.
- `ingestion_runs` has a recent row with `ok = false`, or no row for today.

## Diagnosis

1. Read the failed execution in n8n (Executions tab). The "Pipeline Failed" node output holds the message:
   an HTTP error from the API (timeout, 401, 5xx) or `complaints: <error>` / `recalls: <error>` from the body.
2. Check the last runs in the database:
   ```bash
   docker compose exec -T postgres psql -U postgres -d vsia -c \
     "select kind, started_at, rows_fetched, rows_inserted, ok, left(error, 120) from ingestion_runs order by id desc limit 6;"
   ```
3. Check the API and its logs:
   ```bash
   docker compose ps vsia-api
   docker compose logs --since 2h vsia-api | tail -100
   ```
4. Check NHTSA directly from the VM (no key needed):
   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' -G https://api.nhtsa.gov/complaints/complaintsByVehicle \
     --data-urlencode make=KIA --data-urlencode model=EV6 --data-urlencode modelYear=2022
   ```
   HTTP 400 with `Count: 0` means "no match" (a model string changed), not an outage.

| Finding | Likely cause |
|---|---|
| 401 from the API | n8n credential "VSIA API bearer" does not match `VSIA_API_TOKEN` |
| Connection refused / timeout to `vsia-api` | API container down, restarting, or out of memory (`docker compose ps`, `dmesg | grep -i oom`) |
| NHTSA 5xx or timeouts | NHTSA outage or throttling |
| `rows_fetched = 0` for one vehicle, 400 from NHTSA | NHTSA renamed a model string (research section 1.2) |
| Postgres errors in API logs | Database down or disk full (`df -h`, `docker compose ps postgres`) |

## Mitigation

- Token mismatch: fix the n8n credential, then run the workflow manually ("Execute workflow").
- API down: `docker compose up -d vsia-api`; if it was OOM-killed, see `vm-out-of-capacity.md`.
- NHTSA outage: wait; ingestion is idempotent (duplicates are skipped on `odi_number`), so the next
  scheduled run catches up. To catch up sooner: `docker compose exec vsia-api vsia ingest`.
- Model string change: `docker compose exec vsia-api vsia ingest --refresh-vehicles` re-discovers strings
  at run time.
- Disk full: prune old images (`docker image prune -f`) and old n8n executions (pruning is on, 14 days).

## Rollback

Ingestion only inserts new rows. If a bad run inserted wrong rows, delete them by `ingested_at` window
after taking a backup (`deployment.md`, Backups), then re-run ingestion. If a new API image caused the
failure, redeploy the previous commit: `git checkout <previous-sha>` on the laptop and
`scripts/deploy_vm.sh <ip>`.

## Escalation

Single-owner project: the platform owner handles it. If NHTSA has been unavailable for more than 48 hours,
note the data gap on the dashboard and in the weekly forecast notes, because the missing week will
depress complaint counts and can mask or fake spikes.
