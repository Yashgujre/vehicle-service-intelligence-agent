# ADR-0075: Keep n8n workflows as thin API clients; ship the n8n-native agent as a comparison variant

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer (author)
- **Component:** chat (n8n orchestration)
- **PRD link:** FR-1, FR-4, FR-5, FR-7, FR-9

## Context

ADR-0001 put the triage, RAG and forecasting logic in the Python service. This record decides how the n8n
side is shaped: how much logic lives in workflows, how errors surface, and what the n8n-native AI Agent
workflow is for. n8n Community Edition has no Git sync, the workflows are validated statically (ADR-0008),
and the API runs long synchronous jobs (`/triage/pending` with 200 items, `/forecast/run`).

## Decision

Workflows 01 to 04 contain only triggers, HTTP calls to the API, If branches, small Code nodes that shape
counts and messages, and notifications. Every HTTP node that can fail uses `onError: continueErrorOutput`
plus `retryOnFail`; failure branches notify and then throw so the execution is recorded as failed.
Workflow 05 (AI Agent with Anthropic, Structured Output Parser and an NHTSA HTTP tool) is exported as a
demo and comparison variant; its records are tagged `run_id = n8n-native-<execution>` and it is inactive
by default.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Thin API-client workflows plus an inactive native variant (chosen) | One logic path; workflows are short and reviewable as JSON; failures visible in n8n's execution list | The canvas shows HTTP calls, not prompts |
| B. Native agent as the primary triage path | Matches the PRD picture; visual | Logic duplicated outside tests and eval (ADR-0001); redaction re-implemented in JavaScript |
| C. Retry and error handling only in the API | Simpler workflows | Scheduling failures (API down, timeout) would be invisible; no notification hook |

## Trade-offs accepted

The native variant duplicates a subset of redaction in JavaScript and computes routing from the model's
own confidence only, so its outputs are not comparable to the calibrated Python path without care. Long
synchronous HTTP calls need 15 to 30 minute timeouts in n8n.

## Consequences

Evaluation and model switching stay in Python. Workflow JSON is small enough to diff. The API was extended
for full function: `/forecast/run` returns its spike alerts (and a 409 when the pipeline cannot run yet),
and `GET /search` serves the native agent's second tool. Native records share `triage_records`; evaluation
must filter by `run_id`.

## Revisit when

The batch triage job regularly exceeds 15 minutes (move to an async job endpoint polled by n8n), or a
non-engineer needs to edit triage logic in the canvas.
