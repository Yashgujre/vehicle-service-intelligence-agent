# ADR-0032: Rule-based field extraction for fixed-layout forms; LLM extraction only as a fallback

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** Document parsing (`src/vsia/documents.py`)
- **PRD link:** FR-2 (extract campaign, component, defect, remedy, affected models into a fixed schema)

## Context

FR-2 asks for structured fields from each recall document (`schemas.RecallDocExtraction`). Part 573
reports are federal forms with fixed labels ("Vehicle 1 : 2017-2025 Tesla Model 3", "Description of the
Noncompliance :", "Description of Remedy Program :"), in two layouts (pre-2025 and 2025+). Owner letters
are free-form and differ by manufacturer. The local model is a 3B model; calling it costs about 10 to 40 s
per document and can paraphrase or invent fields.

## Decision

1. Extraction order per document: rules, then LLM (structured output, ADR-0007), first valid result wins.
2. Rules cover both Part 573 layouts and the "What is the issue? / What is the risk? / What will ... do?"
   owner-letter layout.
3. Part 573 reports are processed first. An owner letter whose rules miss is not sent to the LLM when the
   same campaign already has a valid Part 573 extraction (method `covered_by_part573`); the letter is still
   chunked and indexed for retrieval.
4. Campaign number and source URL come from the manifest, never from the model.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Rules first, LLM fallback, skip covered letters (chosen) | Deterministic and free on the authoritative form; LLM only where needed | Rules to maintain when NHTSA changes the form |
| B. LLM for every document | One code path; shows off the model | Slow; 3B model can paraphrase or hallucinate; no gain over exact labels |
| C. Rules only | Fastest | Free-form documents get no fields |

## Trade-offs accepted

The LLM extraction path is exercised less in the default run. Its quality is measured separately by
running it on Part 573 reports and comparing with the rule output (field agreement), rather than trusting
it unmeasured.

## Consequences

Measured on 2026-10-19: Part 573 reports 80 of 80 extracted by rules, all with affected models and model
years; owner letters 8 of 70 by rules, 62 covered by the campaign's Part 573; 0 LLM calls needed.

## Revisit when

Documents without a Part 573 counterpart (technical service bulletins, foreign recalls) are added, or a
form-layout change drops the rule hit rate below 95%.
