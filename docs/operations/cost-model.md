# Cost model

Expected LLM cost per complaint and per month at several volumes, the method behind the token
assumptions, and the budget alarms. Observed costs come from the `llm_calls` table and the evaluation
reports and are **pending evaluation**: no hosted-provider call has been made yet.

Runbook: [cost spike](runbooks/cost-spike.md). Metric definitions: [metrics.md](../evaluation/metrics.md).

## 1. Price table

From `config/settings.yaml` (`llm.providers.*.price_per_mtok`), which states "Prices verified 2026-10-18
(docs/research/02_technical_verification.md section 6)". USD per million tokens.

| Provider | Model | Input | Output | Notes |
|---|---|---|---|---|
| `anthropic` | `claude-haiku-5-5` | 0.10 | 0.50 | |
| `openai` | `gpt-6-luna` | 0.10 | 0.50 | Settings note: `gpt-5-nano` (0.05 / 0.40) is cheaper but its only snapshot shuts down 2026-12-11 |
| `ollama` | `qwen2.5:3b` | 0.00 | 0.00 | Local compute; not deployed on the VM |
| `gemini` | `gemini-3.5-flash-lite` | 0.00 | 0.00 | Free tier, used by the hosted demo (ADR-0088). Paid-tier list price kept as `paid_price_per_mtok`: 0.30 input, 2.50 output (section 7) |
| `groq` | `openai/gpt-oss-20b` | 0.00 | 0.00 | Free tier, hosted demo backup (ADR-0088); no paid price in settings |
| `heuristic` | `tfidf-logreg` | 0.00 | 0.00 | No LLM |

Prices change; when they do, update `config/settings.yaml` with a new verification date and re-run the
scenarios below. `vsia.llm.price()` reads the table at call time, so historical `llm_calls.cost_usd`
values keep the price that applied when they were logged.

## 2. Cost per call and per complaint

Cost of one LLM call, as implemented in `vsia.llm.price()`:

```text
cost_call = input_tokens / 1,000,000 * price_in + output_tokens / 1,000,000 * price_out
```

Triage makes exactly one `complete_json()` call per complaint. That call can include a second attempt when
the first reply fails schema validation; the second attempt resends the full prompt plus the validator
message, and the logged tokens are the sum of both attempts. So, with `r` the schema retry rate:

```text
cost_per_complaint ~= (T_in * price_in + T_out * price_out) / 1,000,000 * (1 + r)
```

where `T_in` and `T_out` are the mean input and output tokens of a first attempt. HTTP-level retries
(429 and 5xx, up to three attempts) that fail before a response do not return usage and are not counted.

Other LLM uses, outside triage:

| Use | Calls | Output cap | Frequency |
|---|---|---|---|
| RAG chat (`vsia.rag`) | 2 per question: `rag_plan` and `rag_answer` | `rag_plan` 200 tokens; `rag_answer` 500 | per user question |
| Recall document extraction (`vsia.documents`) | 1 per parsed document, only when rules-first extraction falls back to the LLM (ADR-0032); input capped at 12,000 characters of document text | 800 | one-off per document |

Chat and extraction token counts have not been measured; use the same formula with their logged tokens.

## 3. Token assumptions: method

1. Measure, do not estimate. Token counts come from the provider's usage fields, logged in `llm_calls`.
   `cost_latency_summary()` gives mean input and output tokens per provider, model and purpose.
2. Tokenizers differ. Ollama reports `prompt_eval_count` and `eval_count` from the Qwen tokenizer; hosted
   providers count with their own tokenizers. Re-measure per provider; do not transfer counts.
3. Input size is dominated by the fixed system prompt (instructions, component glossary, severity rubric)
   and the candidate recall list (up to 12 candidates, 300 characters of summary each); the complaint
   text is truncated to 2,000 characters only for the search query, not for the prompt.
4. Output is capped at `max_output_tokens = 700` (`config/settings.yaml`).

The only triage measurement so far: one Ollama `qwen2.5:3b` triage call on 2026-10-19 logged 2,057 input
tokens and 326 output tokens (`llm_calls`, read-only query). It is a single observation from a different
tokenizer, used below only to size the scenarios.

| Assumption set | `T_in` | `T_out` | Retry factor | Cost per complaint (USD) | Cost per 1,000 complaints (USD) |
|---|---|---|---|---|---|
| A. Observed shape | 2,057 | 326 | 1.0 | 0.0003687 | 0.37 |
| B. Output at cap | 2,057 | 700 | 1.0 | 0.0005557 | 0.56 |
| C. Output at cap, every call retried | 2,057 | 700 | 2.0 | 0.0011114 | 1.11 |

Arithmetic for A at 0.10 / 0.50: 2,057 x 0.10 / 1e6 = 0.0002057; 326 x 0.50 / 1e6 = 0.0001630; sum
0.0003687. Both hosted providers have the same prices, so the table holds for either.

## 4. Volume scenarios

Monthly cost = cost per complaint x complaints per day x 30. For scale, the current corpus holds 10,303
complaints over 249 complete weeks (2022-01-03 to 2026-10-05), about 6 per day for this segment, and the
daily workflow triages at most 200 per run.

| Complaints per day | Per month | A: observed shape (USD/month) | B: output at cap (USD/month) | C: worst case (USD/month) | A per year (USD) |
|---|---|---|---|---|---|
| 50 | 1,500 | 0.55 | 0.83 | 1.67 | 6.73 |
| 500 | 15,000 | 5.53 | 8.34 | 16.67 | 67.29 |
| 5,000 | 150,000 | 55.31 | 83.36 | 166.71 | 672.88 |

At 5,000 per day the daily workflow's limit of 200 complaints per run would also need raising, and the
triage latency SLO would decide whether one VM keeps up.

Not included:

- Infrastructure: the deployment targets OCI Always Free, Pinecone Starter and Streamlit Community Cloud
  (ADR-0080, ADR-0087, ADR-0071), intended to cost nothing; their limits, not money, are the constraint.
  The hosted demo is costed separately in section 7.
- Embeddings: Ollama `nomic-embed-text` is free locally; Pinecone's hosted `llama-text-embed-v2` is limited
  by the Starter plan's embedding-token allowance, with no per-token price in settings.
- Re-runs for evaluation: one full evaluation is 500 triage calls (300 calibration + 200 gold), so about
  0.18 USD under assumption A per hosted provider.

## 5. Budget and alarms

Proposed budget for the portfolio deployment: **10 USD per month** for all hosted LLM use. That covers
assumption C at about 300 complaints per day, chat traffic and several evaluation runs.

| Alarm | Condition | Where |
|---|---|---|
| Provider-side hard limit | Monthly spend limit of 10 USD on each provider account | Provider consoles; the only control that stops spend if the stack misbehaves |
| Daily spend | `sum(cost_usd)` from `llm_calls` for the current UTC day above 0.67 USD (twice the daily share of the budget) | Proposed n8n schedule; see [observability](observability.md#42-proposed) |
| Monthly burn | month-to-date spend above 50%, 80% and 100% of 10 USD | Same query, `created_at` since the first of the month |
| Unit cost | mean `cost_usd` per `triage` call over 24 hours above 3 times the measured mean for that provider | Detects prompt growth or a retry storm |
| Call volume | more than 2 `triage` calls per `ref_id` in 24 hours | Detects re-triage loops (unbounded consumption, OWASP LLM10) |

When an alarm fires, follow the [cost spike runbook](runbooks/cost-spike.md).

## 6. Observed costs

| Provider | Measured cost per 1,000 triages | Source |
|---|---|---|
| `ollama` | 0 by price table | `llm_calls` |
| `anthropic` | measured in `docs/evaluation/reports/<date>-anthropic-gold.md` (pending) | `eval/run_eval.py score` (`cost_per_1000_usd`) |
| `openai` | measured in `docs/evaluation/reports/<date>-openai-gold.md` (pending) | same |

Two numbers will exist once evaluations run, and they differ on purpose:

- `cost_per_1000_usd` in evaluation reports averages `triage_records.cost_usd`, which is 0 for failed LLM
  calls.
- `cost_per_1000()` and the dashboard's "cost per 1,000 calls" average `llm_calls.cost_usd`, which
  includes the tokens spent by failed calls.

For budgeting, use `llm_calls`.

## 7. Hosted demo (zero cost)

The shareable hosted demo (ADR-0088 to ADR-0092, [runbook](runbooks/hosted-demo.md)) costs nothing to run.
Every part is on a free tier:

| Part | Service | Cost | Limit that matters |
|---|---|---|---|
| App hosting | Streamlit Community Cloud | 0 | About 2.7 GB memory and 2 CPU cores per app; sleeps after 12 hours without traffic (ADR-0089) |
| Demo data bundle | GitHub release asset | 0 | One manual upload per data refresh (ADR-0091) |
| Query embeddings | fastembed, in-process | 0 | 0.52 GB model download after a cold start (ADR-0090) |
| Primary model | Google Gemini API free tier, `gemini-3.5-flash-lite` | 0 | See free-tier limits below |
| Backup model | Groq free tier, `openai/gpt-oss-20b` (optional) | 0 | See free-tier limits below |
| Visitor's own key | Visitor's provider account | 0 to the owner | Billed, if at all, to the visitor |

Free-tier limits (checked 2026-10-19; Google calls its limits "not guaranteed"). Google no longer publishes
per-model free-tier request limits; its rate-limits page points to the per-project values in AI Studio:

| Provider | Requests per minute | Requests per day | Tokens | Reset |
|---|---|---|---|---|
| Gemini, `gemini-3.5-flash-lite` | Shown in AI Studio | Shown in AI Studio | Shown in AI Studio | Midnight Pacific |
| Groq, `openai/gpt-oss-20b` | 30 | 1,000 | 8,000 per minute; 200,000 per day | not stated in ADR-0088 |

ADR-0088 sizes one triage call at about 2,400 input and 250 output tokens. Groq's 8,000 tokens per minute allow about 3 triage calls a minute
(ADR-0088), and its 200,000 tokens per day allow about 75 triage calls a day (200,000 / 2,650). These per-call
sizes are estimates from ADR-0088; tokens per call on Gemini and Groq are not yet measured, and chat tokens
per question are not yet measured.

The app protects the shared quota with a cap of 15 AI calls per browser session and 400 calls per provider
per day (ADR-0092). The runbook requires a Gemini key in a project
with no billing account, so exceeding a limit returns errors (HTTP 429), not charges.

**What-if: the same traffic on Gemini's paid tier.** `config/settings.yaml` keeps the paid list price for
`gemini-3.5-flash-lite` as `paid_price_per_mtok`: 0.30 USD input and 2.50 USD output per million tokens
(pricing page, 2026-10-19).
With the ADR-0088 call size:

```text
2,400 x 0.30 / 1e6 = 0.000720 USD
  250 x 2.50 / 1e6 = 0.000625 USD
cost per triage call ~= 0.00135 USD, or about 1.35 USD per 1,000 triage calls
```

If every call were triage-sized, the app's daily cap of 400 calls would cost about 0.54 USD a day. These are what-if figures from list prices and estimated token counts, not observed costs.
