# ADR-0078: Version n8n workflows as exported JSON and validate them statically

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer (author)
- **Component:** chat (n8n orchestration)
- **PRD link:** FR-1, FR-12

## Context

n8n Community Edition stores workflows in its database and has no Git sync. The development laptop
cannot run n8n (ADR-0008), so the workflows could not be imported or executed at build time. Node type
strings and versions were verified from package source (research section 2.2), but one type
(`n8n-nodes-base.httpRequestTool`) is inferred. The triage output schema is a contract (`vsia.schemas`)
that the native workflow embeds as a JSON schema string.

## Decision

Workflows live as JSON in `workflows/n8n/`, one file per workflow, re-exported from the editor after any
change. `scripts/validate_n8n.py` checks required keys, UUID node ids, unique names, verified type
strings and versions (warning on inferred ones), connection integrity, unique webhook paths, Code node
JavaScript syntax, and that the Structured Output Parser schema equals `TriageOutput.model_json_schema()`
with `$defs` inlined.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Exported JSON plus a static validator (chosen) | Runs without n8n; catches typos, broken links and schema drift in CI | Cannot catch parameter-shape errors inside nodes |
| B. Exported JSON only | No extra code | Errors surface only on import, possibly on the VM |
| C. n8n CLI import and execute in CI | Real execution | Needs n8n installed (hundreds of MB) and a database |
| D. Enterprise Git source control | Native sync | Paid feature |

## Trade-offs accepted

Parameter shapes (for example the Schedule cron rule or If conditions) are only as good as common exports;
the first import on the VM is the real test.

## Consequences

Contract changes to `TriageOutput` fail the validator until workflow 05 is updated. The validator should
run in CI next to `pytest`.

## Revisit when

n8n is running on the VM: import every workflow, re-export, and diff against the repository copy to
confirm parameter shapes and the inferred tool type; or Community Edition gains Git sync.
