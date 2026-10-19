# ADR-0044: Silver severity from NHTSA incident flags first, then ordered keyword rules, default S3

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** evaluation (`eval/build_gold.py`: `silver_severity`, `SEVERITY_RULES`)
- **PRD link:** FR-12; severity rubric in `config/settings.yaml`

## Context

The triage agent assigns S1 to S4 using the rubric in `config/settings.yaml`. NHTSA records do not carry
a severity, but they do carry incident flags (crash, fire, injuries, deaths), which map directly to the
rubric's S1 definition. S2 to S4 depend on what happened (unintended braking versus a rattle), which is
only in the free text. No hand labels exist (ADR-0040).

## Decision

`silver_severity()` applies, in order, and stops at the first match:

1. **S1 from flags:** crash, fire, injuries greater than 0 or deaths greater than 0
   (`severity_source = "nhtsa_flags"`, `needs_hand_review = false`).
2. **S1 keywords** (`s1_total_loss`): total or complete loss of power, braking or steering, only when the
   text also has moving context (highway, mph, while driving and similar).
3. **S2 keywords:** phantom or sudden braking and AEB, unintended acceleration, loss of power while
   driving, steering or ADAS jerks and disengagements, brake warnings and restraint or wiper failures.
4. **S3 keywords:** charging and 12 V battery, no-start or no-shift, camera, display, HVAC and leaks,
   doors, locks and lights, mechanical issues and recall-parts availability.
5. **S4 keywords:** noises, trim and paint, infotainment and audio.
6. **Default S3** (`rule_default`) when nothing matches.

Every non-flag label has `severity_source = "rule_keywords"` or `"rule_default"`, records the rule id,
and is marked `needs_hand_review = true`. The rule set is versioned with `silver-v1`.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Flags first, then ordered keyword rules, default S3 (chosen) | High-precision S1; deterministic and auditable; every label explains itself by rule id | Keyword rules miss paraphrase and negation; default S3 hides unknowns |
| B. S1 from flags only, no labels for S2 to S4 | Only high-precision labels | No severity evaluation beyond S1 |
| C. LLM-labelled severity | Handles paraphrase | Circular for an LLM-evaluated system; cost |
| D. Hand labels | Truth | Not available at build time |

## Trade-offs accepted

S2 to S4 silver labels are weak. On the gold split, 25 rows are S1 by flags, 3 are S1 by keywords, and 172
come from S2 to S4 keyword rules or the default; 76 of those are the S3 default with no rule fired
(`data/gold/build_summary.json`). Severity agreement metrics are therefore reported as "versus silver" and
include a within-one-level variant. S1 recall and precision are evaluated against the flags only, on the
LLM's raw severity before the business rule (docs/evaluation/metrics.md).

## Consequences

- The agent's severity business rule (ADR-0062) and the silver S1 label use the same flags, so final
  severity agrees with silver S1 by construction; evaluation uses the LLM's raw severity for S1.
- The rule list is the first thing to change when hand labels show systematic disagreement.

## Revisit when

Hand labels exist for at least 100 gold rows: if keyword-rule agreement with hand severity is below 70%,
replace S2 to S4 silver with hand labels; or the severity rubric in settings changes.
