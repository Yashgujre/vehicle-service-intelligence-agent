# Runbook: human review backlog growing

## Symptom

- Workflow 02 ("VSIA 02 Review queue digest and decisions") reports a backlog above
  `VSIA_REVIEW_BACKLOG_THRESHOLD` (default 25) for several consecutive hours.
- The review share of triaged complaints rises well above its usual level.

## Diagnosis

1. Size, age and confidence of the queue:
   ```bash
   curl -s -H "Authorization: Bearer $VSIA_API_TOKEN" "https://<API_FQDN>/review/pending?limit=200" \
     | python3 -c "import sys,json;r=json.load(sys.stdin);print(len(r), min((x['created_at'] for x in r), default=None))"
   ```
2. Is the routing rate itself up, or are reviewers simply behind?
   ```bash
   docker compose exec -T postgres psql -U postgres -d vsia -c \
     "select date(created_at) d, provider, route, count(*) from triage_records
      where created_at > now() - interval '7 days' group by 1,2,3 order by 1,2,3;"
   ```
3. Reasons for routing: `select reason, count(*) from review_queue where status='pending' group by 1 order by 2 desc;`

| Finding | Likely cause |
|---|---|
| Review share jumped after a deploy | Provider or model changed without its tuned threshold file |
| Many `injection_suspected` reasons | Spam or prompt-injection attempts in new complaints |
| Review share steady, backlog old | Reviewer capacity |
| Spike in one component | Real-world defect cluster (check the forecast alerts) |

## Mitigation

- Missing threshold: copy `data/models/routing_<provider>.json` to the VM with `scripts/deploy_vm.sh <ip> --no-build`
  (it copies routing files into the API volume).
- Reviewer capacity: prioritise by lowest confidence (the queue is already ordered that way) and
  severity S1/S2 first; decisions can be posted in bulk through the webhook
  `POST /webhook/vsia-review` or `POST /review/decision`.
- Temporarily raising `VSIA_CONFIDENCE_THRESHOLD` routes *more* items to review; lowering it auto-accepts
  more. Only lower it with evidence from the evaluation workstream; record the change and the reason.

## Rollback

Restore the previous threshold (remove the override or redeploy the previous routing file). Review
decisions are append-only rows in `labels`, so no rollback is needed for them.

## Escalation

If S1 (critical) complaints wait more than one business day, escalate to the vehicle quality lead: S1
items are the reason the review loop exists.
