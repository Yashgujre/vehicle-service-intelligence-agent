# ADR-0030: Hybrid retrieval (dense + BM25, RRF) behind one store interface; local store by default, Pinecone optional

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** Retrieval (`src/vsia/retrieval.py`)
- **PRD link:** FR-3 (vector index), FR-9 (RAG chat), NFR cost and offline operation

## Context

The PRD names Pinecone as the vector index. The project also has to run with zero keys (ADR-0002), and
recall matching depends on exact tokens that embeddings blur: campaign numbers (`24V935`), part names
(`ICCU`, `TPMS`), FMVSS numbers. Complaint text is informal; recall text is regulatory prose, so lexical
overlap alone also misses matches.

## Decision

1. One `VectorStore` protocol (`upsert`, `search`) with two implementations:
   - `LocalStore`: Ollama `nomic-embed-text` (768-d, L2-normalised, task prefixes `search_document:` /
     `search_query:`) in numpy plus jsonl per namespace, BM25 (`rank_bm25`) over the same records, fused
     with reciprocal rank fusion, k = 60.
   - `PineconeStore`: integrated-embedding index (`llama-text-embed-v2`), SDK v10, dense only.
2. `VSIA_VECTOR_STORE=local|pinecone` selects the store; default `local`.
3. Filters are a flat `{field: value | [values]}` dict, translated to `$eq` / `$in` / `$and` for Pinecone.
4. Vehicle scoping uses one list field, `vehicle_keys = ['MAKE|MODELFAMILY|YEAR']`, so one exact-match filter
   works in both stores and tolerates NHTSA model-string drift (`model_family()` folds `MUSTANG MACH-E BEV`
   and `MUSTANG MACH E` to `MUSTANGMACHE`).

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Hybrid local + optional Pinecone behind one interface (chosen) | Runs offline; exact-token recall from BM25; same code path for the cloud demo | Two stores to keep in step; Pinecone path is dense only |
| B. Pinecone only | Matches the PRD literally; managed | Needs a key for every run; no lexical leg without a sparse index |
| C. Dense only, local | Simplest | Misses campaign numbers and part acronyms |
| D. pgvector in Postgres | One database | SQLite locally has no equivalent; extra extension on the VM |

## Trade-offs accepted

- Vectors from the two embedding models are not comparable, so switching stores means a full re-index.
- The local store loads a namespace into memory; fine at about 11,000 records, not at millions.
- RRF discards score magnitudes; the best dense cosine is kept separately as a confidence signal.

## Consequences

Measured on 2026-10-19 (local store, Apple silicon laptop): recalls namespace 407 records in 24 s;
recall_docs 352 chunks in 64 s. Spot checks returned the correct campaign first for a Tesla TPMS
telltale complaint (24V935) and a Mach-E subframe bolt complaint (21V140).

## Revisit when

The corpus exceeds about 100,000 records locally, or Pinecone sparse-dense hybrid is adopted for the cloud path.
