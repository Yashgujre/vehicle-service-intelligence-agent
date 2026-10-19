# ADR-0060: Triage is a fixed workflow with tool calls, not a free-running agent loop

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** Triage agent (`src/vsia/agent.py`)
- **PRD link:** FR-4 (triage agent with tools), FR-5 (human-in-the-loop routing), FR-6 (model switching), NFR cost and latency

## Context

The PRD calls the triage step an "agent" with two tools: recall lookup for the vehicle and similarity
search over recall text. Every complaint needs the same steps in the same order. A ReAct-style loop lets the
model decide whether and when to call tools, how many times, and when to stop.

## Decision

The triage step is a deterministic pipeline; the LLM is called once per complaint:

1. Redact PII; score prompt-injection risk.
2. Call both tools in code: `recall_lookup` (all recalls for make, model, year) and `recall_search`
   (hybrid retrieval, vehicle-filtered). Merge to at most 12 candidates.
3. One structured-output LLM call (ADR-0007) with the complaint wrapped as untrusted data and the
   candidates listed.
4. Validate: taxonomy normalisation, citation grounding against the candidate list, component-overlap rule
   (ADR-0063), severity business rule (ADR-0062).
5. Calibrated confidence (ADR-0061), route to `auto` or `review`, persist.

The same tools are also exposed as an n8n AI Agent variant (workflow 05, ADR-0075) to show the
model-driven tool-calling pattern; it is not the production path.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Fixed workflow, tools called in code, one LLM call (chosen) | Predictable cost and latency; every step logged; easy to evaluate; small models cope | Model cannot ask for more context |
| B. ReAct loop with tool calling | Flexible; model chooses tools | Variable calls per item; 3B local models call tools unreliably; harder to evaluate and bound |
| C. Multi-agent (extractor, classifier, matcher) | Separation of concerns | Three LLM calls per complaint; more failure points |

## Trade-offs accepted

The model never sees more than 12 candidate recalls. If the right recall is not retrieved, it cannot be
matched; this is measured as retrieval recall@5 separately from the LLM's match accuracy.

## Consequences

Cost per complaint is one LLM call (plus at most one repair retry). Latency is dominated by that call.

## Revisit when

Complaints need multi-step investigation (for example pulling owner history or service records) that a
fixed pipeline cannot anticipate.
