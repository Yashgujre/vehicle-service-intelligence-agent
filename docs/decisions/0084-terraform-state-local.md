# ADR-0084: Keep Terraform state local and gitignored

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer (author)
- **Component:** infra
- **PRD link:** FR-10

## Context

Terraform manages one small environment (network, one VM, one Pinecone index) operated by one person from
one laptop. Remote state would need an OCI Object Storage bucket (S3-compatible backend with customer
secret keys) or a third-party service, created before Terraform can use it.

## Decision

State stays in `infra/terraform/terraform.tfstate`, gitignored together with `terraform.tfvars` and
`.terraform/`. Secrets are kept out of state: the Pinecone key comes from the environment and no secret
is written to instance metadata (ADR-0085). The state file is backed up after each apply.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Local state, gitignored (chosen) | Zero setup; no extra credentials | No locking; lost laptop means re-importing resources |
| B. OCI Object Storage backend | Durable; versioned bucket | Bootstrap problem; customer secret keys to manage; no native locking |
| C. HCP Terraform free tier | Locking and history | Third-party account; state leaves the tenancy |
| D. State committed to Git | Simple sharing | State contains OCIDs and IPs; easy to leak and to conflict |

## Trade-offs accepted

No state locking (only one operator) and a manual backup step.

## Consequences

The Terraform README documents the backup and `terraform import` recovery path. CI cannot run `plan`
against real state.

## Revisit when

A second operator or a CI pipeline needs to run Terraform.
