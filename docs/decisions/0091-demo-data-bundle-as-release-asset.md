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

The first published bundle (release `demo-data-v1`, 2026-10-19) was 62,847,379 bytes, sha256
`a402ef85e9f22ad90ec71059e32605055913f3942eb4aea263d9ac2078d45ee4`. The current one (release
`demo-data-v2`, 2026-10-20 UTC) adds the Gemini calibrator and routing file and is 63,045,915 bytes, sha256
`b37570c5af27b3d2697f4d8ee1b7dd25ec619efa7df3f326742da29a3c8fdb2f`. Both have 75 complaint narratives
changed by redaction.

The bundle is published as a GitHub release asset. The app downloads it on first start when
`VSIA_BUNDLE_URL` is set, verifies `VSIA_BUNDLE_SHA256`, and unpacks only regular files under `data/`
(`vsia.bundle.ensure`). The checksum is mandatory: the bundle contains joblib files, and loading a joblib
file runs code, so an unverified bundle is never installed. If the secret is missing, the download fails or
the checksum does not match, nothing is unpacked, the app shows a warning with the cause and the pages fall
back to the read-only snapshot (ADR-0072). The install is attempted once per server process and per
checksum: the marker `data/.bundle.json` records the installed sha256, and a different
`VSIA_BUNDLE_SHA256` triggers a fresh download, so a data refresh does not depend on the container's disk
being wiped.

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
