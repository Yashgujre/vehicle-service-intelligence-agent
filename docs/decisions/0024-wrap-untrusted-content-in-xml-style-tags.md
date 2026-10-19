# ADR-0024: Wrap untrusted content in XML-style tags after neutralising tag spoofing and chat-template tokens

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** guardrails (`guardrails.wrap_untrusted`), prompts
- **PRD link:** FR-4, FR-9, FR-11

## Context

OWASP LLM01:2025 recommends segregating and labelling untrusted content. VSIA places three kinds of
untrusted text in prompts: complaint narratives (triage), chat questions (RAG), and recall document
text (extraction fallback). The repository is public, so an attacker knows the delimiter names. Small
local models (`qwen2.5:3b`) must still follow the convention, and the same prompts must work on
Anthropic, OpenAI and Ollama.

## Decision

`wrap_untrusted(text, tag)` returns `<tag>\n...\n</tag>` after:

1. removing invisible characters (zero-width and bidirectional controls) and mapping look-alike angle
   brackets to `<` and `>`;
2. replacing any opening or closing form of the same tag (raw, HTML entity, numeric entity, with spaces
   or attributes) with `[<tag> tag removed]`;
3. replacing chat-template tokens (`<|...|>`, `[INST]`, `<<SYS>>`) with `[special token removed]`;
4. validating the tag name against `^[a-z][a-z0-9_]{0,31}$`.

Each system prompt states that text inside these tags is data and never instructions. Tags in use:
`complaint` (triage), `question` (RAG plan and answer), `document` (recall extraction).

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. XML-style tags with neutralisation and a prompt rule (chosen) | Models from all three providers follow tag conventions; cheap; deterministic; tested against 8 spoofing forms | Known tag names; only the wrapped tag is neutralised; depends on the model honouring the rule |
| B. Random per-call boundary strings | Attacker cannot predict the delimiter | Harder to read in logs and tests; small models follow fixed tags more reliably than random tokens |
| C. Datamarking (interleave a marker character through the text) | Strong signal that every token is data | Degrades extraction quality on a 3B model; changes the text the model must quote |
| D. Encode untrusted text (for example base64) | Instructions are not readable as instructions | Small models decode unreliably; extraction of symptoms and mileage suffers |
| E. No delimiting | Simplest | Model cannot distinguish data from instructions |

## Trade-offs accepted

Neutralisation applies only to the block being wrapped. Candidate recall text (`<candidate_recalls>` in
`vsia/agent.py` `_user_message`) and RAG context (`<context>` in `vsia/rag.py` `answer`) are built from
retrieved records and are not passed through `wrap_untrusted` (risk R-09). The detector's
`delimiter_spoof` rule does not list `candidate_recalls` or `question`.

## Consequences

- Tests: `test_wrap_untrusted_basic_shape`, `test_wrap_untrusted_neutralises_tag_spoofing` (8 forms),
  `test_wrap_untrusted_removes_chat_template_tokens`, `test_wrap_untrusted_custom_tag_and_validation`.
- `untrusted_instruction(tag)` provides a standard system-prompt sentence but is not used by the current
  prompts, which carry their own wording; the prompt specs in `docs/llm/prompts/` record that wording.

## Revisit when

- An adversarial evaluation shows tag-escape or role-impersonation success, measured in
  docs/evaluation/ (pending), or
- providers expose a native channel for untrusted content that all three support, or
- retrieved context is wrapped as well (update this record with the new tags).
