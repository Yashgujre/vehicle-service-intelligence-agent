# ADR-0033: Index namespaces and record design; no ground-truth labels in the complaint index

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** Retrieval (`scripts/build_index.py`)
- **PRD link:** FR-3, FR-4 (recall matching), FR-9 (RAG chat)

## Context

Triage needs "which recalls cover this vehicle and look like this complaint". The chat needs similar
complaints and recall text. NHTSA component labels on complaints are the triage ground truth (ADR-0005);
if they were indexed, any retrieval step could leak the answer into the prompt.

## Decision

| Namespace | Unit | Text | Key metadata |
|---|---|---|---|
| `recalls` | campaign x vehicle (API rows) | component, summary, consequence, remedy | `campaign_number`, `component`, `vehicle_keys` |
| `recall_docs` | about 800-token chunk, 100 overlap, of redacted document markdown | chunk text | `campaign_number`, `doc_type`, `page`, `vehicle_keys` |
| `complaints` | one complaint | redacted narrative only | make, model, year, date, crash, fire, `vehicle_keys` |
| `tsbs` | reserved | | not populated: no public bulk TSB source in scope |

- `vehicle_keys` for a document chunk is the union of the campaign's API rows and the Part 573 vehicle list.
- `search_recalls_for_complaint` searches `recalls` and `recall_docs` with the vehicle filter and fuses at
  campaign level, one hit per campaign.
- Complaint records never carry `components_raw` or `component_primary`.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. Separate namespaces per source (chosen) | Per-source filters and fields; scores not mixed across sources | Fusion needed across namespaces |
| B. One namespace, `source` field | One query | Short API records and long chunks compete on one scale |
| C. One record per campaign (vehicle list field) | Fewer records | Text repeated per vehicle anyway in the API; per-vehicle filter simpler |

## Trade-offs accepted

Gold-set complaints are in the complaint index. Triage does not query the complaint namespace, so there
is no leakage path; the chat may cite a gold complaint as a similar case, which is acceptable.

## Consequences

Index sizes on 2026-10-19: recalls 407, recall_docs 352, complaints about 10,300 (redacted narratives).

## Revisit when

TSBs become available (populate `tsbs`), or triage starts using similar complaints as few-shot examples
(then the gold and calibration splits must be excluded from that namespace).
