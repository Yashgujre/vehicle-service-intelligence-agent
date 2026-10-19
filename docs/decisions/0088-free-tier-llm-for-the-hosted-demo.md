# ADR-0088: Use free-tier Gemini for the hosted demo, with Groq as backup, visitor keys and an offline mode

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer (author)
- **Component:** LLM gateway, hosted demo
- **PRD link:** FR-6 (model switching), FR-11 (guardrails), NFR cost

## Context

The project must be shareable: a recruiter or engineer should open a link, run the agent and judge it, with
no setup and at zero cost to the owner. The development default, Ollama with `qwen2.5:3b` (ADR-0006), needs
a machine with a GPU or Apple silicon; free app hosts have neither. Claude and OpenAI (ADR-0006) are paid
per token and have no free tier.

Free hosted options checked on 2026-10-19:

| Provider | Free allowance | Fit |
|---|---|---|
| Google Gemini API, `gemini-2.5-flash-lite` | Free input and output tokens on the free tier (pricing page, 2026-10-19). Limits are shown per project in AI Studio; Google's table as of March 2026 listed 15 requests per minute, 1,000 per day and 250,000 tokens per minute. No card. Quotas reset at midnight Pacific | One triage call is about 2,400 input and 250 output tokens, so the token limit is not binding |
| Groq, `openai/gpt-oss-20b` | 30 requests per minute, 1,000 per day, 8,000 tokens per minute, 200,000 tokens per day (Groq rate-limits page, 2026-10-19) | The token-per-minute limit allows about 3 triage calls a minute; good as a backup |
| Local Ollama | Free, unlimited | Cannot run on a free app host |

Both providers expose an OpenAI-compatible Chat Completions endpoint with `response_format` JSON schema, so
the existing structured-output contract (ADR-0007) carries over unchanged.

## Decision

1. Add `gemini` and `groq` providers to the gateway through one OpenAI-compatible caller
   (`vsia.llm._chat_completions`). Schemas are sent strict and self-contained (`$ref` inlined).
2. The hosted demo uses the owner's free Gemini key (Streamlit secret `GEMINI_API_KEY`). When Gemini answers
   429 (rate or daily quota) and a `GROQ_API_KEY` exists, the triage page retries once on Groq and says so.
3. Visitors can paste their own key (Gemini, Groq, OpenAI or Anthropic) in the sidebar. The key is passed
   per request through `vsia.llm.use_keys()` (a context variable), lives only in that browser session and is
   never written to the database or logs.
4. An "Offline classifier" option runs the same workflow with the TF-IDF baseline (provider `heuristic`), so
   the demo works with no AI provider at all.
5. If every AI path fails, the agent's existing failure mode applies: baseline output, route to human review,
   with the reason shown (ADR-0060, ADR-0064).

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Gemini free tier + Groq backup + visitor key + offline (chosen) | Zero cost; strong small models; works for every visitor; graceful degradation | Shared daily quota; free-tier prompts may be used by Google to improve products |
| B. Visitor key only | No shared quota to protect | Most recruiters will not create an API key, so most visitors see nothing |
| C. Small local model inside the app container | No third-party calls | 2 shared CPU cores: tens of seconds per call and memory limits; poor first impression |
| D. Paid Claude or OpenAI key with a spend cap | Best quality | Not free; a leaked or abused key costs money |

## Trade-offs accepted

- Google states that free-tier content may be used to improve its products. The demo sends only public NHTSA
  complaint text after PII redaction, plus whatever a visitor types; the "Write your own" tab tells visitors
  not to enter personal information.
- Free-tier limits are "not guaranteed" by Google. The demo therefore caps its own use (ADR-0092) and always
  has the offline path.
- Gemini and Groq need their own calibration runs (ADR-0061). Until `python -m eval.run_eval all --provider
  gemini` has run, confidence for Gemini uses the fallback weights and is labelled as such.

## Consequences

- `config/settings.yaml` gains `gemini` and `groq` entries with price 0 (free tier) and the paid list price
  for the cost model.
- `LLMError` now carries the provider's HTTP status, so callers can tell quota errors from other failures.
- The model comparison gains two free cloud models next to the local one.

## Revisit when

Google or Groq change their free tiers, the demo regularly exhausts the daily quota, or the owner chooses to
fund a paid key.
