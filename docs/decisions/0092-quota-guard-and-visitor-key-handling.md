# ADR-0092: Cap shared free-tier use per session and per day; keep visitor keys in the session only

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer (author)
- **Component:** hosted demo, security
- **PRD link:** FR-11, NFR cost, NFR security

## Context

The hosted demo is public. One visitor, or a script, could use up the owner's free Gemini quota for the day,
and everyone after them would get errors. Visitors who paste their own key must be able to trust that it is
not stored or leaked.

## Decision

- **Per session:** at most 15 AI calls on the shared key (`hosted.SESSION_AI_RUNS`). A triage run counts one
  call and a chat question counts two (plan and answer).
- **Per day:** the app counts today's `llm_calls` rows for the provider since midnight Pacific (when Gemini
  quotas reset) and stops using the shared key at `VSIA_HOSTED_DAILY_LLM_CALLS` (default 400, below the
  1,000-per-day free limit, which leaves room for retries and the owner's own runs).
- When a cap is hit, the page says why and offers the two alternatives: the visitor's own key or the offline
  classifier.
- **Visitor keys:** a password field, kept in that browser session's state, passed per request through a
  context variable (`vsia.llm.use_keys`). They are never written to the database, logs or `llm_calls`. The
  gateway's error strings never include request headers, where keys travel.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Session and daily caps in the app (chosen) | No extra service; uses the call log that already exists | A determined user can open new sessions until the daily cap |
| B. No caps | Simplest | One visitor can break the demo for the day |
| C. Login before use | Strong per-user limits | Friction kills a recruiter demo |
| D. External rate limiter or API gateway | Robust | Extra service and cost |

## Trade-offs accepted

The daily cap counts every call for the provider, including calls made with visitors' own keys, so it is
conservative. The session cap resets if a visitor opens a new browser session; the daily cap still holds.

## Consequences

Owner runs that need many calls (evaluation) should run locally with the owner's key, not through the
hosted app.

## Revisit when

Real traffic shows the caps are too tight or too loose, or abuse appears in the Community Cloud logs.
