# ADR-0093: Fall through a chain of free models on the shared key, failing fast between them

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer (author)
- **Component:** hosted demo, LLM gateway
- **PRD link:** FR-11, NFR availability, NFR cost

## Context

On 2026-10-19 the shared Gemini key used its whole daily quota for `gemini-3.5-flash-lite` (the 429 names
`GenerateRequestsPerDayPerProjectPerModel-FreeTier`, value 500). For the rest of that day every AI request
on the public demo fell back to the offline classifier. The same evening Google returned 503 ("This model is
currently experiencing high demand") for most free models it was asked about: `gemini-3.1-flash-lite`,
`gemini-3.1-flash-lite-preview`, `gemini-flash-latest` and `gemini-3.6-flash`. The gateway retried each call
three times with exponential backoff, so a request on an overloaded model took 30 to 60 seconds.

Probes of other models on the same key that evening, one or two triage calls each:

| Model | Result |
|---|---|
| `gemini-3.1-flash-lite` | Valid output when it answered; 503 for part of the evening |
| `gemini-flash-lite-latest` | One success, then 429: it appears to share the main model's quota |
| `gemini-3-flash-preview`, `gemini-3.5-flash` | Invalid JSON twice in a row |
| `gemini-2.5-flash` | 404 for this key |

## Decision

1. Free-tier quotas are per model, so the provider config lists `backup_models` (Gemini:
   `gemini-3.1-flash-lite`). On the host's key the app tries, in order: the chosen model, its backup models,
   then Groq when `GROQ_API_KEY` is set (`hosted.candidates`).
2. The chain moves to the next model only when the provider could not serve the call: 429, 5xx, timeouts
   and connection errors (`hosted.unavailable`). Invalid output does not move on; the agent's own fallback
   (offline classifier, human review) handles it.
3. Every model except the last runs inside `llm.fail_fast()`: no retries and a 30-second timeout, so a
   refused model costs about a second, not half a minute. The last model keeps the normal retries.
4. A model that failed is skipped by every session in the server process for 10 minutes after a 429 and 2
   minutes after an overload.
5. The daily cap (ADR-0092) is counted per model, and rate-limited calls do not count, because Google does
   not charge them against the quota.
6. Only the final result is saved, so a refused attempt never appears in the triage queue.

Backup models reuse the main model's confidence calibrator; the page says so when a backup answered.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Model chain with fail-fast (chosen) | Uses every free quota the key has; no new accounts; quick fall-through | Backup models are not separately calibrated |
| B. Only a second vendor (Groq) | Independent of Google outages | Needs a second account and key; Groq has its own limits |
| C. Retry harder on the main model | Simple | A spent daily quota does not come back until midnight Pacific; retries only add latency |
| D. Paid tier | Reliable | Costs money; the demo must stay free |

A and B combine: the chain ends with Groq when its key is set.

## Consequences

Visitors get an AI answer while any model in the chain can serve it. When none can, they get the offline
classifier with a message that says why. Evaluation results (`eval/run_eval.py`) are for the main model
only.

## Revisit when

A backup model answers a meaningful share of hosted requests (calibrate it separately), or Google changes
which free models the key can use.
