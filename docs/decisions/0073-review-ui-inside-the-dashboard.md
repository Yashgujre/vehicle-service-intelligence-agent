# ADR-0073: Put the human review form inside the dashboard, writing through vsia.review.decide

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer (author)
- **Component:** dashboard, review
- **PRD link:** FR-5, FR-8

## Context

Low-confidence triage records wait in `review_queue`. An analyst must accept or correct each one: the
component from the taxonomy, a severity from S1 to S4, and recall campaigns. Every decision becomes a
label that evaluation reuses. The analyst also needs context: the redacted complaint text, the agent's
output, why the record was routed to review, and which recall candidates the agent saw.

## Decision

The dashboard's Human review page shows pending items, lowest confidence first, with one form per item.

- Component options come from `config/settings.yaml`.
- Severity options are S1 to S4.
- Campaign options are limited to `confidence_signals.candidates`.
- Submitting the form calls `vsia.review.decide(ReviewDecision(...))`.
- Writes are refused when `VSIA_READONLY=1` or in demo mode. The form is disabled and the page says so.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Form in the Streamlit dashboard (chosen) | Context and decision on one screen; reuses the review contract; no new tool | Streamlit has no user accounts; the reviewer name is typed in |
| B. Separate labelling tool (Label Studio, Argilla) | Mature labelling UX, multi-user | Another service and export/import sync with `labels`; heavy for the 12 GB VM |
| C. API only (`/review/decision`), driven from n8n or a notebook | No UI work | Analysts lose context; error-prone |

## Trade-offs accepted

Streamlit has no authentication, so the writable mode is for local or private use only. The public deploy
is read-only. The reviewer is a free-text field.

## Consequences

The dashboard is the only UI that writes. After a decision, caches are cleared so the stats update at once.
The `AppTest` tests submit a correction end to end and check that the read-only mode disables the button.

## Revisit when

More than one reviewer works in parallel, or audit requirements call for authenticated reviewer identity.
