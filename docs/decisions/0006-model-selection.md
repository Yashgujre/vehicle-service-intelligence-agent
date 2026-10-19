# ADR-0006: Model choices: Claude Haiku 5.5, OpenAI gpt-6-luna, local qwen2.5:3b

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer
- **Component:** LLM gateway
- **PRD link:** FR-6, Tech Stack and Cost, Success metric "LLM cost per 1,000 complaints < $1"

## Context

The PRD names Claude Haiku 5.5, OpenAI GPT-5 nano and an Ollama model. Verification on 2026-10-18
(docs/research/02_technical_verification.md, section 6) found: `claude-haiku-5-5` costs $0.10 input and
$0.50 output per million tokens and supports native JSON-schema output; `gpt-5-nano` is cheapest
($0.05 / $0.40) but its only snapshot shuts down on 2026-12-11; `gpt-6-luna` ($0.10 / $0.50) is OpenAI's
recommended cost-sensitive model. The laptop is a 16 GB M1 with about 7 GB of free disk.

## Decision

| Role | Model | Why |
|---|---|---|
| Primary hosted | `claude-haiku-5-5` | Cheapest current Claude; native structured output; Batch API halves cost |
| Comparison hosted | `gpt-6-luna` | Same price class; will exist after December 2026; strict JSON schema |
| Local and free | `qwen2.5:3b` (1.9 GB) | Strong JSON adherence for its size; fits disk and RAM next to everything else |
| Embeddings (local) | `nomic-embed-text` (274 MB, 768 dimensions) | Small, good retrieval quality, served by the same Ollama |

Expected hosted cost at about 1,500 input and 300 output tokens per complaint: about $0.30 per 1,000
complaints on either hosted model (illustrative estimate; measured values go in the eval report).

## Options considered

| Option | Pros | Cons |
|---|---|---|
| gpt-5-nano | Cheapest per token | Removed from the API on 2026-12-11; demo would break |
| qwen3:4b or qwen3.5:4b locally | Likely better quality | 2.5 to 3.3 GB; thinking mode adds latency; disk is tight |
| llama3.2:3b locally | Similar size | Weaker JSON adherence in community reports (unverified for this task) |

## Trade-offs accepted

The local model is small, so local accuracy is a floor. Model quality ranking for this task is not
assumed; the evaluation report decides.

## Revisit when

The eval shows the local model below the auto-routing target, more disk is available (try qwen3.5:4b),
or prices change (re-check the pricing pages before each paid run).
