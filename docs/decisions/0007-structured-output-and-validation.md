# ADR-0007: Native structured output per provider, Pydantic re-validation, one repair retry

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer
- **Component:** LLM gateway
- **PRD link:** FR-4 ("output always matches the JSON schema"), FR-6

## Context

FR-4 requires every triage output to match a JSON schema. All three providers now support schema-
constrained output (Anthropic `output_config.format`, OpenAI Responses `json_schema` strict, Ollama
`format`), but each accepts a different subset of JSON Schema keywords. A 3B local model can still
produce semantically invalid values (a component outside the taxonomy, a made-up campaign number).

## Decision

1. One Pydantic model per output (`schemas.TriageOutput`, `schemas.RecallDocExtraction`) is the contract.
2. The gateway sends a cleaned schema (strips `default`, `title`, numeric and length bounds, `pattern`; in
   OpenAI strict mode, marks every property required and forbids extra keys).
3. Every reply is re-validated with the full Pydantic model, including the stripped constraints.
4. On a validation failure, retry once with the validator's error appended. A second failure raises,
   is logged with `ok=False`, and the record goes to human review.
5. Semantic checks (taxonomy membership, campaign numbers present in retrieved context) run after
   schema validation in the agent.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Native structured output + re-validation + one retry (chosen) | Highest schema adherence; provider-agnostic contract; bounded cost | Small extra cost on retries; schema cleaning to maintain |
| B. Prompt-only JSON ("reply in JSON") | Works everywhere | Frequent malformed output on small models |
| C. Tool/function calling to force JSON | Widely supported | Superseded by native JSON output on all three providers |
| D. Unlimited retries | Higher success rate | Unbounded cost and latency |

## Trade-offs accepted

Constraints removed from the provider schema (for example the campaign-number pattern) are enforced only
after the call, so a reply can fail validation and cost a retry.

## Consequences

Schema validity becomes a measured metric (share of calls with `ok=True` on the first attempt, and after
the retry) in the evaluation report.

## Revisit when

All providers accept the full schema (drop the cleaning), or the retry rate exceeds 5% on a provider.
