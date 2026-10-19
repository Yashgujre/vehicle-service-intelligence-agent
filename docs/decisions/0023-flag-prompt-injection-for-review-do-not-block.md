# ADR-0023: Flag suspected prompt injection and route to human review; never block or drop the record

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** guardrails, triage agent (`guardrails.detect_injection`, `agent.triage`)
- **PRD link:** FR-5 (human review), FR-11 (guardrails)

## Context

Every complaint narrative is untrusted text that ends up in an LLM prompt (OWASP LLM01:2025, indirect
prompt injection). A narrative could tell the model to lower severity, skip review or reveal its prompt.
At the same time, each complaint is a public safety record; silently discarding one could hide a real
defect. Real complaints use trigger-like language innocently: "the system prompt electrical system
failure", "you are now driving with a fogged up windshield", "the dealer said to ignore it".

Measured on 2026-10-19 over 10,303 loaded complaints: 0 flagged at the 0.5 threshold; weak rule hits
below threshold were `visit_url` 3, `system_prompt_mention` 1, `you_are_now` 1.

## Decision

1. `detect_injection()` scores each narrative with 15 weighted regex rules combined as a noisy-OR and
   flags at 0.5. It returns rule ids only, never matched text, so the result is safe to persist.
2. A flag never blocks ingestion and never drops the record. It adds the review reason "possible prompt
   injection in complaint text", which forces `route = review`. The model's own `injection_suspected`
   field has the same effect.
3. The record is still triaged normally, so the reviewer sees a full proposal.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Flag and route to review (chosen) | No safety record is lost; false positives cost a review, not data; reviewers see the rule ids | An attacker's text still reaches the model once; relies on the review queue being worked |
| B. Block or drop flagged records | Attacker text never reaches the model | A false positive deletes a public safety complaint; attackers adapt phrasing anyway |
| C. Strip suspicious spans before the LLM call | Model sees cleaner text | Alters the evidence a reviewer and the model need; easy to bypass with paraphrase |
| D. A second model as an injection classifier | Better recall on paraphrase | Extra cost and latency per complaint; the classifier is itself an LLM exposed to the same text; needs its own evaluation |
| E. No detector; rely on wrapping and output validation | Nothing to maintain | No signal for review or monitoring |

## Trade-offs accepted

The detector is lexical. A paraphrased English override and a Spanish override both scored 0.0 in a
probe on 2026-10-19 (`docs/security/guardrails.md` section 3.2). Those cases rely on the other layers:
spotlighting (ADR-0024), output validation, citation grounding (ADR-0025), the severity rule (ADR-0062)
and calibrated confidence (ADR-0061).

## Consequences

- Tests: `test_injection_examples_are_flagged` (10 attacks), `test_benign_complaints_are_not_flagged`
  (10 benign complaints), `test_injection_matches_hold_rule_ids_not_text`,
  `test_detector_threshold_is_configurable`.
- `confidence_signals.injection_score` is stored on every triage record for monitoring.
- The agent compares `inj.score >= 0.5` directly (`vsia/agent.py` line 165) rather than using
  `InjectionSignal.flagged`, so the detector's threshold argument is not configurable on this path yet.

## Revisit when

- Flagged records exceed 1% of a week's triage volume (review load), or
- an adversarial evaluation set shows a detector miss rate that the other layers do not catch, measured
  in docs/evaluation/ (pending), or
- a small, local injection classifier fits within the dependency budget (option D).
