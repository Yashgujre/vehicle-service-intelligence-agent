# ADR-0087: Create the Pinecone index with Terraform

- **Status:** Accepted
- **Date:** 2026-10-18
- **Deciders:** AI workflow engineer (author)
- **Component:** infra
- **PRD link:** FR-3, FR-10

## Context

Cloud retrieval uses a Pinecone integrated-embedding index (`llama-text-embed-v2`, text field
`chunk_text`, AWS `us-east-1`, the only Starter-plan region). `vsia.retrieval.PineconeStore` can also
create the index on first use. Provider `pinecone-io/pinecone` 5.0.0 supports integrated embedding only
through the `spec` + `embed` style (research section 4.3).

## Decision

`infra/terraform/pinecone.tf` declares the index (name from `pinecone_index_name`, default `vsia`, matching
`PINECONE_INDEX`) with `spec.serverless {aws, us-east-1}` and `embed {llama-text-embed-v2, text =
chunk_text}`, behind a `manage_pinecone_index` switch. If the application created the index first, it is
imported (`terraform import 'pinecone_index.vsia[0]' vsia`).

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Terraform owns the index (chosen) | Index settings reviewed in code next to the VM; one `apply` builds the cloud footprint | Two creators (Terraform and the app) must agree on settings; destroy deletes the data |
| B. Application creates it on demand | No Terraform provider | Settings hidden in code paths; no plan/diff |
| C. Create it by hand in the console | Fast | Not reproducible |

## Trade-offs accepted

`terraform destroy` deletes the index and its records (rebuildable from Postgres). The `spec` style is
planned for deprecation by Pinecone, so a provider upgrade may need a rewrite.

## Consequences

The Pinecone resource passed `terraform validate` against provider 5.0.0 in isolation (2026-10-18). The
API key is read from `PINECONE_API_KEY` and never stored in tfvars or state.

## Revisit when

Pinecone supports integrated embedding in the `schema` + `deployment` style, or the index moves to a paid
plan with another region.
