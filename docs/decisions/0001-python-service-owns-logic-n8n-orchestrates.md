# ADR-0001: Keep triage logic in a Python service; n8n orchestrates and calls it

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer
- **Component:** cross-cutting (agent, orchestration)
- **PRD link:** FR-1, FR-4, FR-5, FR-6, FR-7, FR-9, FR-12

## Context

The PRD places the triage agent inside an n8n AI Agent node. n8n Community Edition is a good scheduler,
webhook host and integration canvas, but logic built only in the canvas is hard to unit-test, hard to
diff in code review (Community Edition has no Git sync), and cannot be run by the evaluation script
without n8n running. FR-12 requires one command that reproduces every metric, and FR-6 requires the
same gold set to run on three model providers.

## Decision

The triage workflow (redaction, retrieval, recall lookup, LLM call, validation, confidence, routing) is a
Python package (`vsia`) exposed through a FastAPI service and a CLI. n8n owns schedules, webhooks,
retries and notifications, and calls the service over HTTP. A second, n8n-native variant of the triage
workflow (AI Agent node with tool sub-nodes) is exported for comparison and demo, but it is not the
system of record.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Python service, n8n orchestrates (chosen) | Unit-testable; evaluation runs without n8n; one code path for batch eval and live triage; versioned in Git | Two runtimes to operate; n8n canvas shows less of the logic |
| B. Everything in the n8n AI Agent node | Visual; fastest to prototype; matches the PRD picture literally | Eval needs n8n running; prompts and schemas live in JSON blobs; no unit tests; model comparison means editing nodes |
| C. Python only, cron instead of n8n | Fewest moving parts | Loses the orchestration, webhook and human-in-the-loop integration story the project exists to show |

## Trade-offs accepted

The n8n canvas is thinner than in the PRD picture. Anyone reading only n8n sees HTTP calls, not prompts.
We mitigate with the n8n-native variant and with sequence diagrams in `docs/architecture/`.

## Consequences

Evaluation, model switching and guardrail tests run in plain Python. n8n workflows stay small and
exportable. The FastAPI service becomes a container in Docker Compose.

## Revisit when

A non-engineer needs to change the triage logic without a code change, or n8n adds Git-backed workflow
versioning to Community Edition.
