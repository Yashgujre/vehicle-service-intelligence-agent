# Runbook: VM out of capacity (OCI host capacity, memory or disk)

Three different problems share the word "capacity". Identify which one first.

## Symptom

- A. `terraform apply` fails on `oci_core_instance.app` with `Out of host capacity` (no VM yet).
- B. Containers restart repeatedly, `docker compose ps` shows `unhealthy` or `restarting`, the VM is slow,
  or `dmesg` shows OOM kills.
- C. Writes fail with "No space left on device".

## Diagnosis

```bash
# B: memory
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}'
free -h; swapon --show
sudo dmesg -T | grep -i -E 'killed process|out of memory' | tail
docker inspect --format '{{.Name}} OOMKilled={{.State.OOMKilled}} restarts={{.RestartCount}}' $(docker ps -aq)

# C: disk
df -h /; docker system df
sudo du -sh /var/lib/docker/volumes/* | sort -h | tail
```

Also watch for idle reclamation: Oracle may reclaim an Always Free instance whose 95th-percentile CPU,
network and memory utilisation all stay below 20% for 7 days (research section 8.1).

## Mitigation

A. Host capacity (Terraform):
1. Set `availability_domain_index` to 1, then 2, in `terraform.tfvars` and apply again.
2. Retry later: `until terraform apply -auto-approve; do sleep 300; done`.
3. Start smaller (`instance_ocpus = 1`, `instance_memory_gbs = 6`) and scale up when capacity returns
   (`shape_config` updates in place). At 6 GB, stop open-webui and mlflow until then:
   `docker compose stop open-webui mlflow`.

B. Memory:
1. Identify the container at its limit. Open WebUI and the API are the usual candidates; the API peaks
   during `/forecast/run`.
2. Raise that container's `mem_limit` and lower another (keep the total under about 10 GB), then
   `scripts/deploy_vm.sh <ip> --no-build`.
3. Reduce load: lower the `/triage/pending` batch in workflow 01 (default 200), and keep the MLflow server
   at one worker.
4. Swap (2 GB from cloud-init) is a buffer, not capacity; sustained swapping means limits must change.

C. Disk:
1. `docker image prune -af` (old API builds), `docker builder prune -f`.
2. n8n execution data is pruned after 14 days (`EXECUTIONS_DATA_MAX_AGE=336`); lower it if needed.
3. Grow the boot volume (`boot_volume_gbs`, up to the 200 GB Always Free total), then `sudo growpart`
   and `sudo resize2fs` per Oracle's instructions.

## Rollback

Revert the `mem_limit` or Terraform variable change and redeploy. Volume data is unaffected by container
restarts or limit changes.

## Escalation

If host capacity is unavailable for days in the home region, the Always Free A1 allowance cannot move to
another region. Options: keep the laptop mode for demos, or use a small paid shape temporarily (record the
cost decision in a new ADR).
