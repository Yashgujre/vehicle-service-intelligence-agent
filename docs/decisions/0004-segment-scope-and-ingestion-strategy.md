# ADR-0004: Scope to EV and hybrid SUVs and pickups; ingest via the API with runtime model discovery

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer
- **Component:** ingestion
- **PRD link:** Data Sources (scope decision), FR-1

## Context

The full complaints file is 357 MB. The PRD scopes to one segment, complaints received 2022 to 2026,
to stay inside every free tier. Verification showed NHTSA complaint model strings are exact per model
year (`MUSTANG MACH-E` for 2022, `MUSTANG MACH-E BEV` for 2023 onward; Tesla uses three spellings), that
recall model strings differ from complaint strings, and that "no match" returns HTTP 400 with an empty
result rather than 200.

## Decision

1. Segment: electric and hybrid SUVs and pickups from 8 makes (Ford, Tesla, Rivian, Hyundai, Kia,
   Chevrolet, Toyota, Volkswagen), model years 2021 to 2026, complaints filed on or after 2022-01-01.
   Defined in `config/settings.yaml`.
2. Resolve model strings at run time from `/products/vehicle/models` (complaint and recall issue types),
   filter by regex patterns plus aliases, cache to `data/raw/scoped_vehicles.json`.
3. Store the canonical model name from each complaint's own product record, not the query string.
4. Query recalls using those canonical names (they work for the recall API) plus the resolved strings.
5. Treat HTTP 400 as an empty result and never retry it; retry only 429, 5xx and transport errors.
6. Exclude ambiguous canonical models after load (plain `ESCAPE` mixes gas and hybrid trims).
7. Idempotent loads: skip existing ODI numbers; log fetched, inserted, duplicate and filtered counts to
   `ingestion_runs` on every run.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. API with runtime discovery (chosen) | Small, current data; same client serves the daily job and the agent's recall tool | Many small calls; model-string quirks to handle |
| B. Flat-file backfill (FLAT_CMPL.zip, 357 MB) | Complete history in one download | Disk-heavy on this laptop; still needs filtering; daily freshness needs the API anyway |
| C. Hard-coded model strings | Simple | Breaks every model year; silently misses complaints |

## Trade-offs accepted

The flat-file backfill path is documented but not run (disk). Complaint counts depend on NHTSA's model
naming, and some hybrid owners file under the non-hybrid model name (for example RAV4), so the segment
under-counts hybrids. Treating 400 as empty could hide a real client error; the daily row-count log
makes a sudden drop visible.

## Consequences

Measured at build time: 10,303 complaints after exclusions and 200 recall campaigns (407 vehicle rows).
A re-run inserted 0 rows and skipped 13,367 duplicates. Fixing the 400 handling cut the recall pass from
more than 15 minutes (retries with backoff) to 46 seconds.

## Revisit when

NHTSA publishes an official recall-documents API, or the segment needs gas trims or more makes.
