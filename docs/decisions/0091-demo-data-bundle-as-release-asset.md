# ADR-0091: Ship the demo data as a checksummed release asset, not in Git

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer (author)
- **Component:** hosted demo, data
- **PRD link:** FR-1, FR-3, FR-11 (PII)

## Context

The hosted agent needs the database (complaints, recalls, recall documents, forecasts), the vector index
and the classifier. Together they are about 85 MB uncompressed (database 16 MB, index 43 MB, classifier
25 MB) and change whenever data is re-ingested or models retrained. `data/` is gitignored on purpose.
Re-ingesting from NHTSA and re-embedding 10,303 complaints inside a free container on every cold start
would take many minutes and depend on NHTSA uptime.

## Decision

`scripts/build_demo_bundle.py` (`vsia.bundle.build`) packs one `tar.gz`:

- a copy of `data/vsia.db` with every complaint narrative passed through `guardrails.redact()`;
- the recalls, recall_docs and complaints index namespaces;
- the classifier and every `routing_*.json` and calibrator.

The first build on 2026-10-19 was 62,837,362 bytes, with 75 complaint narratives changed by redaction.

The bundle is published as a GitHub release asset. The app downloads it on first start when
`VSIA_BUNDLE_URL` is set, verifies `VSIA_BUNDLE_SHA256`, and unpacks only regular files under `data/`
(`vsia.bundle.ensure`).

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Release asset with checksum (chosen) | Repo stays small; versioned; tamper-evident; fast download | One manual upload per data refresh |
| B. Commit `data/` to Git | Simplest | 85 MB per refresh accumulates in history forever; unredacted DB risk |
| C. Git LFS | Versioned with code | Free LFS bandwidth is small; Community Cloud LFS support adds risk |
| D. Rebuild from NHTSA at boot | Always fresh | Minutes of cold start; NHTSA dependency; embedding cost on 2 CPUs |

## Trade-offs accepted

The hosted data is as old as the last bundle. The bundle and the code must agree on the schema; the
checksum pins one exact bundle per deploy.

## Consequences

To refresh the demo: rebuild, upload as a new release asset, update the two secrets, reboot the app
(`docs/operations/runbooks/hosted-demo.md`).

## Revisit when

The data needs to be fresher than a manual refresh allows, or the bundle grows past a few hundred MB.
