# ADR-0031: PDF parsing with pypdf by default, tesseract OCR for scans, LlamaParse when a key is present

- **Status:** Accepted
- **Date:** 2026-10-19
- **Deciders:** AI workflow engineer
- **Component:** Document parsing (`src/vsia/documents.py`)
- **PRD link:** FR-2 (parse recall documents with LlamaParse)

## Context

The PRD names LlamaParse. No LlamaCloud key is configured on the build machine, and the project must run
offline (ADR-0002). The corpus is 150 NHTSA PDFs for 80 campaigns: 80 Part 573 Safety Recall Reports
(machine-generated forms with a text layer) and 70 owner notification letters. Ten owner letters are
scanned images with no text layer.

## Decision

1. `parse_pdf()` uses LlamaParse (markdown output) when `LLAMA_CLOUD_API_KEY` is set and
   `llama-cloud-services` is installed; otherwise `pypdf` text extraction.
2. When `pypdf` returns under 200 characters, the pages are rasterised at 300 dpi with `pypdfium2` and read
   with the `tesseract` CLI (parser recorded as `pypdf+tesseract`).
3. Output is markdown with `<!-- page N -->` markers so chunks keep a page citation.
4. Mail-merge barcodes and repeated running headers are dropped; the text is redacted
   (`guardrails.redact`) before it is stored or embedded.

## Options considered

| Option | Pros | Cons |
|---|---|---|
| A. pypdf + tesseract default, LlamaParse optional (chosen) | Zero keys; deterministic; scans covered | Layout (tables) flattened to text |
| B. LlamaParse only | Best layout fidelity; handles scans natively | Paid key on every run; network dependency |
| C. Unstructured / Docling | Rich layout models | Heavy install on a disk-constrained laptop |

## Trade-offs accepted

Tables in Part 573 reports (vehicle lists, chronology) become plain lines. The extraction rules (ADR-0032)
are written against that plain text, so a switch to LlamaParse needs a check that the rules still match.

## Consequences

Measured on 2026-10-19: 150 documents, 481 pages parsed in about 30 s; 140 via pypdf, 10 via OCR;
799 redactions applied (sample owner names and addresses, company phone numbers).

## Revisit when

A LlamaCloud key is available (run both parsers and compare extraction agreement), or documents with
complex tables become in scope (technical service bulletins).
