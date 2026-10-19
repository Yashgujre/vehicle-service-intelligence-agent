# ADR-0082: Terminate TLS with Caddy, using sslip.io host names when there is no domain

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer (author)
- **Component:** infra
- **PRD link:** FR-9, FR-10, NFR security

## Context

Open WebUI logins, the n8n editor, webhook bearer tokens and the API token all cross the internet. The
Streamlit Community Cloud dashboard calls the API from outside, and browsers increasingly refuse mixed or
plain-HTTP content. The project may not own a domain. The OCI free load balancer could terminate TLS but
needs certificates managed separately.

## Decision

A Caddy container is the only service with public ports (80, 443). It obtains Let's Encrypt certificates
automatically for three host names (`CHAT_FQDN`, `N8N_FQDN`, `API_FQDN`) and proxies to Open WebUI, n8n
and the API. Without a domain, the host names use sslip.io (`chat.<ip-with-dashes>.sslip.io`), which
resolves to the VM's IP. Terraform outputs the names.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Caddy with automatic certificates (chosen) | Five-line config per host; renewals automatic; small image | One more container (256 MiB limit) |
| B. No TLS, plain HTTP on ports | Simplest | Tokens and passwords in clear text; browsers warn; unacceptable for a public demo |
| C. nginx plus certbot | Familiar | Renewal cron, more config, two moving parts |
| D. OCI flexible load balancer with a certificate | Managed | Certificate lifecycle still manual; extra OCI resources to model |

## Trade-offs accepted

sslip.io is a third-party DNS service and shares Let's Encrypt rate limits with other users; a real domain
removes both concerns (set `domain` in Terraform). Caddy's tag (`caddy:2-alpine`) is not covered by the
research file.

## Consequences

Port 80 must stay open for the ACME HTTP challenge and redirects. Caddy's certificate store is a named
volume (`caddy-data`) so restarts do not re-issue certificates.

## Revisit when

A domain is bought (switch `domain`), certificate issuance hits rate limits, or a second VM needs load
balancing.
