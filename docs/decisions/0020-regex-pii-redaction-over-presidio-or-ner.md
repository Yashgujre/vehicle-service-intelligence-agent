# ADR-0020: Redact PII with tested regular expressions, not Presidio or a named-entity model

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** guardrails (`src/vsia/guardrails.py` `redact`)
- **PRD link:** FR-11 (guardrails), NFR privacy

## Context

Owner complaint narratives are public NHTSA records, but owners sometimes type contact details, full
VINs, plates and names into them. AGENTS.md rule 4 requires redaction before any text reaches an LLM, an
embedding model or a log line. The constraints:

- The pipeline must run with zero keys and no network (AGENTS.md rule 5), on a laptop with about 7 GB
  free disk; any dependency over about 100 MB needs approval (rule 7).
- Redaction runs on every triage, every search query, index builds over 10,303 complaints, and dashboard
  reads, so it must be fast and deterministic.
- NHTSA already masks many personal fields as `[XXX]` (669 complaints). Measured on 2026-10-19, the
  detector finds PII in 75 of 10,303 complaints (0.73%), mostly addresses and phone numbers
  (`docs/security/pii-handling.md` section 6).
- Domain text is dense with things that look like PII to a generic detector: 17-character part numbers,
  invoice ids, GPS coordinates, mileage, campaign numbers, "Dr." as Drive, "Thank you Tesla".

## Decision

Use a single standard-library function, `redact()`, built from regular expressions with callable
checks (Luhn and card prefix, vanity-number length, sign-off stop list, "Dr." disambiguation). It
returns typed placeholders (`[PHONE]`, `[EMAIL]`, ...) and per-type counts, is idempotent, and is covered
by positive and false-positive tests for every type.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Regex and standard library, test-driven (chosen) | No dependency, no network; deterministic and testable to the exact string; 10,303 complaints redacted and scanned for injection in 5.57 s; rules tuned against real domain false positives | Misses PII without a lexical cue (names without "my name is", lowercase names), non-US formats, categories not modelled (SSN, driver licence, date of birth) |
| B. Microsoft Presidio with a spaCy model | Wider recall for names and locations; extensible recognisers; standard reference | Default English spaCy model is several hundred MB, above the AGENTS.md threshold; NER tags vehicle makes, models and dealer names as entities, so domain false positives need custom deny lists; slower per record; output varies with model version |
| C. Hosted PII detection API | High recall, no local model | Sends unredacted text to a third party in order to remove PII; needs a key and network, violating the zero-key rule; per-call cost |
| D. LLM-based redaction | Understands context | Sends unredacted text to an LLM, the exposure redaction is meant to prevent; non-deterministic; cost on every record |
| E. No redaction; rely on NHTSA masking | Nothing to maintain | 75 loaded complaints still contain detectable PII |

## Trade-offs accepted

Recall is traded for precision, determinism and zero footprint. Names without a cue, lowercase names,
non-US phone numbers, SSNs, driver licence numbers and dates of birth pass through unchanged (probe
results in `docs/security/pii-handling.md` section 7). Business phone numbers and dealer addresses are
redacted as if personal.

## Consequences

- Every new PII format needs a rule plus a positive test and false-positive guards in
  `tests/test_guardrails.py`.
- Counts per type are available for monitoring (`measure_corpus()`, `confidence_signals.pii_redactions`).
- Precision and recall against a hand-labelled sample are not yet measured: measured in
  docs/evaluation/ (pending).
- The native n8n workflow re-implements a subset in JavaScript and can drift from this function.

## Revisit when

- A hand-labelled sample of at least 200 complaints shows redaction recall below 90%, or
- a non-public data source (for example dealer repair orders or call transcripts) is added, where PII
  prevalence will be far higher than 0.73%, or
- a Presidio-class detector becomes available under the 100 MB dependency budget.
