# ADR-0080: Run the cloud stack with Docker Compose on one Always Free A1 VM

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer (author)
- **Component:** infra
- **PRD link:** FR-10, NFR cost

## Context

The cloud deployment must host Postgres, n8n, MLflow, the VSIA API and Open WebUI at zero cost. The OCI
Always Free A1 allowance was cut to 2 OCPUs and 12 GB in total around 2026-06-15 (research section 8.1).
The workload is small (about 10,000 complaints, a daily batch, a weekly retrain, light chat), one person
operates it, and running a local model on the VM would consume most of the memory.

## Decision

One `VM.Standard.A1.Flex` instance (2 OCPU / 12 GB, Ubuntu 24.04 aarch64) runs
`infra/compose/docker-compose.yml`. Every container has a `mem_limit` (total 8.25 GiB), a healthcheck, a
restart policy and a named volume. Images are pinned to verified multi-arch tags. The API container uses
hosted LLMs and Pinecone; Ollama is not run on the VM.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Docker Compose on one VM (chosen) | Smallest overhead; one file to read; matches the PRD; easy to debug with `docker compose logs` | Single point of failure; manual rolling updates |
| B. k3s on the same VM | Kubernetes skills on display; declarative rollouts | Control plane uses roughly 0.5 to 1 GB and CPU we do not have spare; more YAML for five services |
| C. Two 1-OCPU / 6 GB VMs | Separates data from apps | Open WebUI and the API would each fit poorly in 6 GB with the rest; cross-VM networking and two hosts to patch |
| D. Managed services (OCI Container Instances, managed Postgres) | Less host maintenance | Not in the Always Free allowance |

## Trade-offs accepted

No high availability: a VM reboot means a few minutes of downtime, acceptable for a portfolio and
internal-tool workload. Memory limits are planned, not measured.

## Consequences

Capacity incidents follow `docs/operations/runbooks/vm-out-of-capacity.md`. A 2 GB swap file from
cloud-init absorbs short spikes. Measure real usage with `docker stats` after the first week and adjust.

## Revisit when

Sustained memory use exceeds 10 GB, more than one person needs to operate the stack, or the free
allowance changes again.
