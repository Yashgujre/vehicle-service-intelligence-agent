# ADR-0077: Protect n8n webhooks with header auth; keep the API token in an n8n credential

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer (author)
- **Component:** chat (n8n orchestration)
- **PRD link:** FR-5, FR-9, NFR security

## Context

The n8n host is public (Caddy, `N8N_FQDN`) so that reviewer forms and external callers can reach the
review and chat webhooks. An unauthenticated webhook would let anyone spend LLM credits (`/chat`) or write
review labels (`/review/decision`). n8n also needs the API's bearer token (`VSIA_API_TOKEN`) for every call.

## Decision

Every webhook (vsia-chat, vsia-review, vsia-triage-native) uses the Webhook node's header authentication
with a Header Auth credential `Authorization: Bearer <N8N_BEARER>`. The API token is stored in a separate
Header Auth credential ("VSIA API bearer") attached to every HTTP Request node, not in an environment
variable. Only non-secret settings (API base URL, thresholds, notification URL) come from `$env`.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Header auth credentials for webhooks and API calls (chosen) | Secrets encrypted with `N8N_ENCRYPTION_KEY`; not readable through expressions; one place to rotate | Credentials must be re-linked after import (placeholder ids) |
| B. Token in `$env.VSIA_API_TOKEN` | No credential setup on import | Any workflow editor can read it in an expression; it appears in execution data if echoed |
| C. No webhook auth, rely on obscure paths | Simplest | Paths leak through logs and browser history; cost and integrity risk |
| D. Keep n8n private (SSH tunnel only) | Smallest attack surface | No external reviewer form; editor access becomes awkward |

## Trade-offs accepted

Import is a two-step process (import, then select credentials). One shared webhook bearer is used by all
callers; per-caller tokens would need more credentials.

## Consequences

Token rotation touches: `.env`, both n8n credentials, the Open WebUI valve and Streamlit secrets (listed in
`docs/operations/runbooks/cost-spike.md`). The n8n editor itself is protected by n8n's owner account.

## Revisit when

There is more than one external caller that needs separate revocation, or n8n is moved behind single
sign-on.
