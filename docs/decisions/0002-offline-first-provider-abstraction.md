# ADR-0002: Offline-first: every external service has a local fallback behind one interface

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer
- **Component:** cross-cutting
- **PRD link:** Goal 4, FR-2, FR-3, FR-6, Risks table (LLM APIs need a payment method)

## Context

At build time no API keys were available (Anthropic, OpenAI, Pinecone, LlamaCloud). The PRD budget is
about $10, and its risk table already suggests developing on Ollama and paying only for final runs.
The system must still be demonstrable end to end.

## Decision

Each external dependency sits behind a small interface with a local implementation that is the default:

| Capability | Hosted implementation | Local default |
|---|---|---|
| LLM | Claude (`claude-haiku-5-5`), OpenAI (`gpt-6-luna`) | Ollama `qwen2.5:3b` |
| Embeddings and vector search | Pinecone integrated index (`llama-text-embed-v2`) | Ollama `nomic-embed-text` + NumPy + BM25 |
| PDF parsing | LlamaParse v2 (cost-effective tier) | pypdf |
| Database | Postgres (VM) | SQLite (laptop) |
| Experiment tracking | MLflow server (VM) | MLflow with a SQLite store |

Selection is by environment variable only (`VSIA_LLM_PROVIDER`, `VSIA_VECTOR_STORE`, key presence).

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Interfaces with local defaults (chosen) | Runs free with zero keys; tests need no network; model comparison is a config flip | Two code paths per capability to keep correct; hosted paths are untested until keys exist |
| B. Hosted services only | One code path; best quality | Nothing runs without keys and a card; tests need network |
| C. Local only | Simplest | Misses FR-6 model comparison and the Pinecone/LlamaParse parts of the PRD |

## Trade-offs accepted

Hosted code paths (Pinecone, LlamaParse, Claude, OpenAI) are written against verified documentation but
were not exercised at build time. Local quality (a 3B model) is lower than Claude or OpenAI, so local
metrics are a floor, not the expected production number.

## Consequences

Every metric in the evaluation report states the provider and model it came from. When keys are added,
the same eval command produces the hosted numbers for the comparison table.

## Revisit when

Keys are available: run `vsia eval --provider anthropic` and `--provider openai`, and record any defects
found in the hosted paths as follow-up decisions.
