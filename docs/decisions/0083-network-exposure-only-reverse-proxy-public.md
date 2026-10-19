# ADR-0083: Expose only the reverse proxy; keep Postgres on an internal network and MLflow behind SSH

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer (author)
- **Component:** infra
- **PRD link:** FR-10, NFR security

## Context

The VM has a public IP. Postgres holds every record and n8n credentials; MLflow has no built-in
authentication; the API enforces a bearer token on all endpoints except `/health`. Several services need
outbound internet (NHTSA, LLM providers, Pinecone), Postgres does not.

## Decision

Two Docker networks: `backend` (`internal: true`, no egress) and `frontend` (normal bridge). Postgres joins
only `backend`. n8n, the API, Open WebUI and MLflow join both. Caddy joins only `frontend` and is the only
service publishing public ports. MLflow publishes `127.0.0.1:5000` for SSH tunnels. The OCI security list
allows 22 from `admin_cidr` only, and 80/443 from anywhere.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Proxy-only exposure, internal backend network, SSH tunnel for MLflow (chosen) | Smallest public surface; Postgres cannot reach or be reached from the internet | Admin needs SSH for MLflow |
| B. Publish every service port, rely on the security list | Easy local-style access | MLflow and Postgres reachable if the security list is ever loosened |
| C. MLflow behind Caddy with basic auth | Browser access | Another secret to manage; MLflow is used weekly by one person |

## Trade-offs accepted

Viewing MLflow needs `ssh -L 5000:127.0.0.1:5000 ubuntu@<ip>`. Containers on both networks can still reach
the internet, so a compromised app container is not egress-restricted.

## Consequences

`docker compose config` shows exactly which ports are published (verified on the laptop). Changing
`admin_cidr` when the admin's IP changes is a `terraform apply`.

## Revisit when

More people need MLflow access (add Caddy with authentication), or egress filtering becomes a requirement.
