# ADR-0085: Bootstrap the VM with cloud-init; deliver secrets over SSH with a deploy script

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer (author)
- **Component:** infra
- **PRD link:** FR-10, NFR security

## Context

A new VM needs Docker, the Compose plugin, a host firewall change for 80/443 (OCI Ubuntu images ship with
restrictive iptables rules, per community guidance), the repository, and the `.env` file with provider
keys. OCI instance metadata (`user_data`) is visible in the console to tenancy administrators and is stored
in Terraform state.

## Decision

Terraform passes a templated `cloud-init.yaml` as `user_data`. It installs `docker.io`,
`docker-compose-v2`, git and rsync, adds 2 GB of swap, opens 80/443 in iptables, clones the repository
when `repo_url` is set, and starts the stack only if `.env` already exists. `scripts/deploy_vm.sh` copies
`.env` (mode 600) over SSH, syncs or pulls the code, and runs `docker compose up -d --build`. It is
idempotent and refuses to run while placeholder secrets remain.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. cloud-init for packages, SSH script for secrets and deploys (chosen) | Secrets never in metadata or state; repeatable; same script for every redeploy | Two steps on first deploy |
| B. Secrets in instance metadata, read by cloud-init | Fully automatic first boot | Secrets in state and console; rotation needs metadata updates |
| C. Manual provisioning over SSH | Nothing to write | Not repeatable; easy to forget the firewall step |
| D. Ansible | Idempotent, rich modules | Another tool for one host |
| E. OCI Vault for secrets | Proper secret store | More resources and IAM policy for a single VM |

## Trade-offs accepted

The first deployment needs the laptop to run the deploy script. cloud-init changes do not re-run on an
existing VM (Terraform ignores `user_data` changes to avoid replacing the instance).

## Consequences

Redeploys are `scripts/deploy_vm.sh <ip>` (or `--no-build` for `.env`-only changes). The API image builds
on the VM (arm64), so nothing is built or pulled on the laptop.

## Revisit when

More than one VM exists, or a managed secret store becomes available at no cost.
