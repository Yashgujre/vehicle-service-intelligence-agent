# ADR-0090: Embed queries in-process with the same nomic model (ONNX), not a hosted embedding API

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer (author)
- **Component:** retrieval
- **PRD link:** FR-3, FR-9, NFR cost

## Context

The local index (ADR-0030, ADR-0033) holds 10,303 complaint, 407 recall and 352 recall-document vectors from
Ollama `nomic-embed-text` (768 dimensions). The hosted demo has no Ollama, but every search still needs a
query vector from the same model, or the vectors are not comparable.

## Decision

`VSIA_EMBED_PROVIDER=fastembed` makes `vsia.retrieval` embed with `fastembed` and the ONNX export of
`nomic-ai/nomic-embed-text-v1.5`, in-process, with the same task prefixes. The hosted app sets this
automatically when it boots from a bundle. Local development keeps Ollama.

Evidence (`scripts/check_embed_parity.py`, 2026-10-19), re-embedding stored documents and comparing them
with the stored Ollama vectors:

| Model | Namespace | n | Min cosine | Mean cosine | Self top-1 |
|---|---|---|---|---|---|
| nomic-embed-text-v1.5 (fp32, 0.52 GB) | recalls | 40 | 1.00000 | 1.00000 | 1.00 |
| | recall_docs | 40 | 1.00000 | 1.00000 | 1.00 |
| | complaints | 40 | 1.00000 | 1.00000 | 1.00 |
| nomic-embed-text-v1.5-Q (quantized, 0.13 GB) | recalls | 20 | 0.94707 | 0.95175 | 0.85 |
| | recall_docs | 20 | 0.93577 | 0.94323 | 1.00 |
| | complaints | 20 | 0.94480 | 0.95508 | 1.00 |

"Self top-1" is the share of re-embedded documents whose nearest stored vector is their own.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. fastembed fp32 nomic (chosen) | Identical vectors; no key; no network per query | 0.52 GB model download on cold start |
| B. fastembed quantized nomic | 4x smaller | Vectors drift (cosine about 0.95; recalls self top-1 0.85) |
| C. Gemini embedding API | No model in the container | Re-embed the whole corpus; ties search to a key and its quota |
| D. Pinecone integrated embeddings (ADR-0087) | Managed | Another account and key; separate index to keep in sync |
| E. BM25 only in the cloud | Nothing to download | Loses the dense half of hybrid retrieval; results differ from local |

## Trade-offs accepted

The first search after a cold start waits for the model download (about 20 seconds measured locally on a
home connection; not measured on Community Cloud).

## Consequences

`retrieval.set_embedder(None)` now restores the configured default rather than always Ollama. Re-run the
parity script whenever the Ollama model or fastembed version changes.

## Revisit when

fastembed or Ollama change the model export, or memory on the host becomes the bottleneck.
