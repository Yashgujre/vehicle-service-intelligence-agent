# ADR-0022: Keep the first 11 characters of a VIN and redact the serial

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** guardrails (`src/vsia/guardrails.py` `_VIN` rule)
- **PRD link:** FR-4 (recall linking), FR-11, NFR privacy

## Context

A 17-character VIN has a fixed structure: positions 1 to 3 are the World Manufacturer Identifier,
4 to 8 the vehicle descriptor section, 9 the check digit, 10 the model year, 11 the assembly plant, and
12 to 17 the production serial. The serial identifies one physical vehicle and, through registration
records, its owner. The first 11 characters are shared by every vehicle of the same configuration,
year and plant.

NHTSA publishes this prefix itself: the complaints feed carries a VIN prefix that VSIA stores in
`complaints.vin_prefix` (10,243 of 10,303 loaded complaints have one; lengths 9 to 11 characters).
Owners sometimes also type the full VIN into the narrative: the 2026-10-19 corpus measurement found 5 VIN
matches in 5 complaints. The prefix carries signal for triage and recall matching (configuration, model
year, plant), which recall scopes are often defined by.

## Decision

`redact()` matches a full 17-character VIN (no I, O or Q; at least two digits; check digit 0 to 9 or X at
position 9) and replaces only positions 12 to 17, producing `<first 11 characters>[VIN]`. A partially
masked VIN such as `3GNKDHRK4RSXXXXXX` is treated the same way.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Keep positions 1 to 11, redact the serial (chosen) | Matches what NHTSA already publishes; keeps configuration, year and plant for triage; removes the part that identifies one vehicle | Prefix plus other details in the narrative (city, dealer, date) narrows the set of vehicles |
| B. Redact the whole VIN | Simplest; no residual identifier | Loses information NHTSA publishes anyway; diverges from the `vin_prefix` column |
| C. Keep the whole VIN | Maximum information | The serial is a persistent identifier of a person's vehicle |
| D. Hash the full VIN | Allows joining repeat complaints for one vehicle | A VIN space per prefix is small (one million serials), so an unsalted hash is reversible by enumeration; a salted hash adds key management |

## Trade-offs accepted

The prefix is retained in prompts, embeddings and stored text. Combined with other narrative details it
narrows, but does not identify, the vehicle. Lowercase VINs are not matched (`pii-handling.md` section 7).

## Consequences

- Tests: `test_vin_keeps_published_11_char_prefix`, `test_partially_masked_vin_is_still_redacted`, and the
  false-positive guard `The 11-character prefix 5YJYGDEE2MF is published by NHTSA.`
- Known inconsistencies, not yet fixed: the native n8n workflow 05 replaces the whole VIN with `[VIN]`
  (option B), and `vsia/nhtsa.py` line 86 stores `vin_prefix` as returned without truncating it to 11
  characters (risk R-27).

## Revisit when

- NHTSA changes what it publishes in the VIN prefix field, or
- the project ingests data in which full VINs are common (for example repair orders), where repeat-vehicle
  linking would justify option D with a managed salt.
