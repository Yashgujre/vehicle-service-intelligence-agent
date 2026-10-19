# ADR-0076: Open WebUI pipe calls the n8n chat webhook and waits for one JSON answer

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer (author)
- **Component:** chat
- **PRD link:** FR-9, FR-10

## Context

The PRD puts Open WebUI in front of the RAG assistant. Open WebUI Pipe functions can return a string, a
generator (streamed), or a dict (research section 3.2). The API's `POST /chat` returns one JSON object
`{answer, citations, refused, ...}` after two LLM calls (plan, then answer), so there are no tokens to
stream from the service today. Whether n8n's Webhook and Respond to Webhook pair streams chunked output
end to end is unverified. Citations must be visible and checkable.

## Decision

The pipe posts `{question, messages, user_id}` to `http://n8n:5678/webhook/vsia-chat` with header auth,
waits for `{answer, citations, refused}`, renders the answer with a numbered Sources list, and emits one
`source` event per citation plus status events. It never raises into the chat: failures return a short
message. Recalls link to `https://www.nhtsa.gov/recalls?nhtsaId=<campaign>`; complaints show the ODI
number only because there is no stable public deep link.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Pipe to n8n webhook, non-streaming (chosen) | Shows the orchestration layer; n8n can add logging, rate limits or routing later; verified response path | Extra hop and latency; no token streaming |
| B. Pipe straight to the API `/chat` | One hop fewer; simplest | Bypasses n8n, weakening the orchestration story; the API token would live in Open WebUI |
| C. Streaming through n8n | Better perceived latency | Unverified in n8n; the API does not stream anyway |
| D. Open WebUI "OpenAI-compatible connection" to an API shim | Native model picker integration | Needs a new OpenAI-format endpoint; citations harder to render |

## Trade-offs accepted

Users see a status line, then the full answer, typically after several seconds. Only the latest user
message is used; the router is single-turn.

## Consequences

The pipe is unit-tested with mocked `httpx` (`tests/test_openwebui_pipe.py`). The n8n bearer token is an
admin valve in Open WebUI. Changing the API's response shape requires updating workflow 04 and the pipe.

## Revisit when

The API gains a streaming endpoint and n8n streaming is verified, or users report answer latency above
15 seconds at the median.
