# ADR-0026: Protect the API with one bearer token and the n8n webhooks with header auth

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** guardrails (API edge), chat and orchestration (`src/vsia/api.py` `auth`; n8n webhooks)
- **PRD link:** FR-5, FR-9, FR-10, NFR security

## Context

The VM exposes three host names through Caddy (ADR-0082, ADR-0083): Open WebUI, n8n and the VSIA API.
Every API route except `/health` either spends LLM credit (`/triage`, `/triage/pending`, `/chat`),
writes records (`/review/decision`, `/ingest/daily`, `/forecast/run`) or reads data (`/search`,
`/review/pending`). Callers are few and known: n8n workflows, the Open WebUI pipe (through n8n), the
operator, and the dashboard. There is one operator and no per-user data. The laptop must run with zero
configuration (AGENTS.md rule 5). ADR-0077 already decides how n8n stores the API token and protects its
webhooks; this record covers the API side and links the two.

## Decision

1. The API checks `Authorization: Bearer <VSIA_API_TOKEN>` with a FastAPI dependency (`vsia.api.auth`)
   on every route except `/health`. A wrong or missing token returns HTTP 401.
2. On the VM the token is mandatory: `docker-compose.yml` fails to start without `VSIA_API_TOKEN`. On the
   laptop, an unset token disables the check for local development.
3. n8n holds the token in a Header Auth credential, encrypted with `N8N_ENCRYPTION_KEY`, never in `$env`
   (ADR-0077).
4. n8n webhooks (`vsia-chat`, `vsia-review`, `vsia-triage-native`) use Webhook header auth with a separate
   bearer, `N8N_BEARER`, which the Open WebUI pipe sends from its valve (ADR-0077).

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. One static API bearer plus n8n header auth (chosen) | Small code (a five-line dependency); works for n8n, curl and the pipe; secrets encrypted in n8n; rotation is documented | Shared secret: no per-caller revocation; caller identity (for example the reviewer name) is asserted, not authenticated |
| B. OAuth 2.0 or OpenID Connect with per-user identity | Real identities; reviewer accountability | An identity provider to run or rent; heavy for one operator |
| C. Mutual TLS between n8n and the API | Strong service identity | Only covers internal calls; external callers and the dashboard still need another mechanism |
| D. Per-caller API keys stored in the database | Per-caller revocation and audit | Key management code and an admin path to build and secure |
| E. Network-only protection (Caddy basic auth, IP allow lists) | No application code | Credentials or IP lists at the proxy only; the API is open to anything inside the Docker networks |

## Trade-offs accepted

- One token for all API callers and one for all webhook callers; a leak requires rotating everywhere it
  is used (`.env`, both n8n credentials, the Open WebUI valve, Streamlit secrets).
- `ReviewDecision.reviewer` is free text, so review labels are not bound to an authenticated person
  (risk R-18).
- The API fails open when the variable is unset, which is safe only because compose makes it mandatory.
- The comparison is a plain string comparison, not constant-time (`src/vsia/api.py` line 20).
- `/health` is unauthenticated and reports provider, model, vector store and threshold.

## Consequences

- No automated test covers the auth dependency yet.
- Rate limiting is not part of this decision; there is none at Caddy or in the API (risk R-16).
- `N8N_BLOCK_ENV_ACCESS_IN_NODE` is `false` so workflows can read non-secret settings from `$env`, which
  also exposes `N8N_ENCRYPTION_KEY` and the n8n database password to workflow editors
  (`docker-compose.yml` lines 61, 63, 72; risk R-17). This weakens point 3 for anyone with editor access.

## Revisit when

- More than one external caller or more than one reviewer needs separate revocation or attribution
  (move to D or B), or
- a token is exposed (rotate, then reconsider D), or
- the review UI becomes multi-user, or
- the n8n editor is moved behind single sign-on (ADR-0077 trigger).
