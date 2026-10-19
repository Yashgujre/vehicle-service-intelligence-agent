# PII handling

- **Status:** Current as of 2026-10-19
- **Owner:** AI workflow engineer (guardrails workstream)
- **Code:** `src/vsia/guardrails.py` (`redact`, `RedactionResult`, `measure_corpus`)
- **Tests:** `tests/test_guardrails.py` (redaction section: 22 positive cases, 26 false-positive guards,
  idempotence, multi-type counts, speed)
- **Decisions:** ADR-0020 (regex redaction instead of Presidio or NER), ADR-0021 (redact before the LLM,
  embedding and storage), ADR-0022 (keep the 11-character VIN prefix)
- **Standards:** OWASP LLM02:2025 Sensitive Information Disclosure; Microsoft Presidio as the reference
  alternative; structure follows `docs/research/01_documentation_process_research.md` (PII handling row:
  categories, detection method, redaction points, logging rules)

## 1. What personal data VSIA sees

VSIA processes public NHTSA owner complaints and recall documents. NHTSA already masks many personal
fields before publication, writing `[XXX]` in their place (669 of the 10,303 loaded complaints contain
that mask). What remains is incidental: owners sometimes type a phone number, an email address, a dealer
or home address, a full VIN, a licence plate or a name into the narrative. Recall documents (Part 573
reports and owner letters) carry company phone numbers, sample owner names and addresses.

The project rule (AGENTS.md rule 4) is: call `vsia.guardrails.redact()` on complaint text before it
reaches an LLM, an embedding model or a log line, and never log prompt text.

## 2. PII categories handled by `redact()`

`PII_LABELS = ("EMAIL", "CARD", "VIN", "PHONE", "ADDRESS", "PLATE", "NAME")`. Rules run in this order;
earlier rules win because their placeholders never re-match later rules.

| Order | Label | Placeholder | What is matched | Guard against false positives |
|---|---|---|---|---|
| 1 | EMAIL | `[EMAIL]` | `local@domain.tld` | Look-behind stops matches inside longer tokens |
| 2 | CARD | `[CARD]` | 13 to 19 digits with optional single spaces or dashes | Kept only if the Luhn check passes **and** the prefix matches a card network (4, 51-55, 22-27, 34, 37, 6011, 65), so invoice, tracking and GPS digit runs survive |
| 3 | VIN | `<first 11 characters>[VIN]` | 17-character VIN alphabet (no I, O, Q), at least two digits, check digit (0-9 or X) at position 9 | The first 11 characters are kept (ADR-0022); all-caps words are excluded by the two-digit rule |
| 4 | PHONE | `[PHONE]` | US 10-digit numbers with optional `+1`, brackets and separators; toll-free vanity numbers such as `1-800-FLOWERS` | Word-character look-arounds stop matches inside invoice ids; vanity numbers need exactly 7 characters after the code |
| 5 | ADDRESS | `[ADDRESS]` | House number, optional direction, one to four Titlecase or ordinal words, a street suffix (St, Ave, Rd, Dr, Ln, Blvd, Hwy, ...), optional unit; P.O. boxes | Excludes times (`5:00 PM CT`), road descriptions (`2 Lane Rd`, `45 MPH road`, `4 Wheel Drive`) and "National Highway" |
| 6 | PLATE | `<label>[PLATE]` | 3 to 9 alphanumerics (optionally split by one space or dash) after "license plate", "plate number", "tag number" | Requires the label, at least one digit and one letter |
| 7 | NAME | `<cue>[NAME]` | Titlecase names after a cue: a title (Mr, Mrs, Ms, Mx, Dr.), "my name is", a label (`Owner Name:`), or a sign-off (Thanks, Regards, Sincerely, ...) | Stop list of words that follow sign-offs but are not names (for example "Thank you Tesla", "Sincerely, [XXX]"); "Dr." after a capitalised word is treated as "Drive" |

Properties verified by tests:

- **Typed placeholders:** downstream code and reviewers can see what was removed
  (`test_redacts_each_pii_type`).
- **Idempotent:** redacting twice changes nothing and reports zero new matches
  (`test_redaction_is_idempotent`).
- **Counts per type:** `RedactionResult.counts` holds only the types found
  (`test_counts_cover_multiple_types_in_one_text`).
- **Domain text survives:** model years, 12V, mileage, ODI numbers, campaign numbers, VIN prefixes,
  drive modes, speeds, invoice and part numbers, GPS coordinates, software versions, tyre sizes and the
  NHTSA FOIA footer are not touched (`test_false_positive_guards`, 26 cases).
- **Speed:** 10,000 mixed complaints in under 20 seconds (`test_redaction_is_fast_enough_for_10k_complaints`);
  the full corpus measurement below ran redaction plus injection detection over 10,303 complaints in
  5.57 seconds.

## 3. Detection method

Regular expressions and the standard library only, with callable replacements for the checks a regex
cannot express (Luhn, card prefix, vanity length, sign-off stop list, "Dr." disambiguation). No model,
no network, no extra dependency. The choice against Microsoft Presidio or a named-entity model is
recorded in ADR-0020: the measured PII prevalence is low (section 6), NHTSA pre-masks the most sensitive
fields, the dev laptop has about 7 GB free disk, and a deterministic function is testable to the exact
string.

## 4. What is kept on purpose

| Kept | Why | Decision |
|---|---|---|
| First 11 characters of a VIN (WMI, vehicle descriptor, check digit, model year, plant) | NHTSA itself publishes this prefix in `vin_prefix`; it identifies the vehicle configuration needed for recall matching, not the individual vehicle. The serial (last 6 characters) is redacted | ADR-0022 |
| `complaints.vin_prefix` column | Published by NHTSA as an 11-character prefix (loaded values: 10,243 non-null, length 9 to 11) | ADR-0022 |
| Make, model, model year, dates, city and state names | Needed for triage and forecasting; not personal on their own | n/a |
| NHTSA `[XXX]` masks | Already anonymised upstream; left untouched | n/a |
| Public recall text in the `recalls` table (summary, consequence, remedy) | Manufacturer and NHTSA text. It contains public hotline numbers (see section 6.3) that are not personal data, so it is embedded and shown to the LLM as candidate context without redaction | ADR-0021 |

## 5. Redaction points

The DFD (`data-flow-diagram.md` section 4) marks these as RP1 to RP8.

| Point | Data | Before reaching | Code | Test |
|---|---|---|---|---|
| RP1 | Complaint narrative in triage | LLM prompt, recall search query, TF-IDF classifier | `src/vsia/agent.py` line 101 (`guardrails.redact(c.summary)`); `src/vsia/classifier.py` `_redacted` | None at agent level; function tests in `test_guardrails.py` |
| RP2 | Any vector search query | Embedding model and vector store (local or Pinecone) | `src/vsia/retrieval.py` `search_recalls_for_complaint` (line 526), `search_complaints` (line 566), `search_sources` (line 575) | None |
| RP3 | Complaint narratives at index build | Embedding model (Ollama or Pinecone integrated embedding) and stored record text | `scripts/build_index.py` `complaint_records` (line 92) | None |
| RP4 | Parsed recall document markdown | Storage in `recall_documents.markdown`, rule and LLM extraction, chunking and embedding | `src/vsia/documents.py` `process` (lines 255 to 257) | None |
| RP5 | `GET /search` query | Vector store | `src/vsia/api.py` line 100 | None |
| RP6 | Complaint text and free-text model output shown in the dashboard; demo snapshot | Screen; public Streamlit Community Cloud snapshot | `app/data.py` `redact_obj`, `complaint_text`; `scripts/export_demo_snapshot.py` | `test_triage_detail_redacts_text_and_output`, `test_pending_reviews_live_has_candidates_and_redacted_text` (`tests/test_app_data.py`) |
| RP7 | Span log attributes | Python logs | `src/vsia/observability.py` `_scrub` (text-bearing keys replaced with `[omitted]`, other strings redacted) | `test_timed_logs_genai_attributes_and_scrubs_text` |
| RP8 | Complaint in the native n8n triage variant | Anthropic via n8n | `workflows/n8n/05_triage_agent_native.json`, node "Redact PII" (JavaScript subset: email, VIN, card, phone, plate) | `scripts/validate_n8n.py` checks syntax only |
| Logs | LLM calls | `llm_calls` table | `src/vsia/llm.py` `complete_json` logs provider, model, purpose, tokens, cost, latency, ok, error, prompt version, reference id; never prompt or reply text | `test_llm_calls_never_store_prompt_text` |

Where redaction does **not** happen (tracked in the risk register):

| Location | What stays unredacted | Risk id |
|---|---|---|
| `complaints.summary` | Narrative as published by NHTSA. Kept raw by design so redaction rules can improve and be re-run | Accepted (public source) |
| `src/vsia/rag.py` lines 54 and 109 | Chat question sent to the LLM (wrapped, not redacted) | R-03 |
| `src/vsia/agent.py` line 88 | Heuristic fallback copies 160 characters of the raw narrative into `extracted.symptom` | R-04 |
| Open WebUI volume, n8n execution data | Chat questions and full message history (pipe sends `messages` and `user_id`) | R-05 |
| `llm_calls.error`, `confidence_signals.llm_error` | Validator messages that quote `input_value=` from model output | R-06 |
| `src/vsia/nhtsa.py` line 86 | `vin_prefix` stored as returned, not truncated to 11 characters | R-27 |
| LlamaCloud upload (`documents.py` lines 59 to 63) | Whole PDF before parsing, when `LLAMA_CLOUD_API_KEY` is set | R-28 |

## 6. Measured redaction counts

All numbers below were produced on **2026-10-19** against the local database `data/vsia.db` (10,303
complaints filed 2022-01-02 to 2026-10-15; 200 recall campaigns; 150 parsed recall documents). No LLM
was called.

### 6.1 Complaints (`complaints.summary`)

Command (repository root):

```bash
.venv/bin/python -c "
import json
from vsia.guardrails import measure_corpus
print(json.dumps(measure_corpus(), indent=2))
"
```

Equivalent to `python -m vsia.guardrails`. Result:

| PII type | Matches | Complaints containing the type |
|---|---|---|
| EMAIL | 6 | 5 |
| CARD | 0 | 0 |
| VIN | 5 | 5 |
| PHONE | 24 | 20 |
| ADDRESS | 53 | 49 |
| PLATE | 0 | 0 |
| NAME | 6 | 6 |
| **Total** | **94** | **75 complaints with any type** |

- Share of complaints with at least one detected PII item: **0.73%** (75 of 10,303).
- Complaints already containing NHTSA's `[XXX]` mask: **669**.
- Run time for redaction plus injection detection over the corpus: **5.57 seconds**.
- The same run reports injection signals: 0 complaints flagged; rule hits below the threshold:
  `visit_url` 3, `system_prompt_mention` 1, `you_are_now` 1 (see `guardrails.md`).

These are detector counts, not verified true positives. Precision and recall of `redact()` against a
hand-labelled sample are measured in docs/evaluation/ (pending).

### 6.2 Recall documents (`recall_documents.markdown`, stored after redaction)

Command: count typed placeholders in the stored markdown and re-run `redact()` to check for residual
matches.

```bash
.venv/bin/python -c "
import sqlite3
from vsia.guardrails import redact
con = sqlite3.connect('data/vsia.db')
labels = ['EMAIL','CARD','VIN','PHONE','ADDRESS','PLATE','NAME']
ph = dict.fromkeys(labels, 0); docs_with = 0; resid = {}
rows = con.execute('select markdown from recall_documents').fetchall()
for (md,) in rows:
    md = md or ''
    found = False
    for k in labels:
        n = md.count('[' + k + ']'); ph[k] += n; found = found or n > 0
    docs_with += found
    for k, v in redact(md).counts.items(): resid[k] = resid.get(k, 0) + v
print(len(rows), ph, docs_with, resid)
"
```

| Placeholder in stored markdown | Occurrences |
|---|---|
| `[PHONE]` | 405 |
| `[ADDRESS]` | 301 |
| `[NAME]` | 71 |
| `[VIN]` | 21 |
| `[EMAIL]` | 1 |
| `[CARD]`, `[PLATE]` | 0 |

- All 150 stored documents contain at least one placeholder.
- Re-running `redact()` over the stored markdown finds **0** further matches, which confirms the
  documents were redacted before storage and that redaction is idempotent on real data.
- Most `[PHONE]` matches are manufacturer and NHTSA contact numbers printed on the forms; they are
  redacted anyway because the rule does not distinguish business from personal numbers.

### 6.3 Recall API text (`recalls` summary, consequence and remedy; not redacted by policy)

Same method, run over the 200 distinct campaigns: 199 campaigns contain at least one phone-shaped match
(223 `PHONE` matches) and 1 `EMAIL` match. These are public hotline and manufacturer contact details in
NHTSA's recall text, which is why this table is deliberately not redacted (section 4).

## 7. Known limitations

Probed on 2026-10-19 with `.venv/bin/python -c "from vsia.guardrails import redact; print(redact(<text>))"`.
Each of these inputs passed through **unchanged**:

| Input | Why it is missed |
|---|---|
| `my name is john smith` | Name rules require Titlecase tokens |
| `I am Maria Gonzalez from Austin` | No cue ("my name is", title, label or sign-off) |
| `call +44 20 7946 0958` | Phone rule covers US 10-digit numbers only |
| `email me at jdoe at gmail dot com` | Obfuscated email |
| `I live on Main Street near the park` | No house number |
| `VIN 1hgcm82633a004352` | VIN rule is upper-case only |
| `DL number D1234567` | Driver licence numbers are not a category |
| `my SSN is 123-45-6789` | Social Security numbers are not a category |
| `born 04/12/1980` | Dates of birth are not a category (dates are kept for triage) |
| `plate 8ABC123` | Plate rule needs "license plate", "plate number" or "tag number" |

Other limitations:

- Business phone numbers and dealer addresses are redacted as if personal; this loses some context but
  is the conservative choice.
- Counts measure detector output only; there is no hand-labelled PII test set yet.
- The native n8n workflow (RP8) uses a JavaScript subset with no address or name rules, and it replaces
  the whole VIN instead of keeping the 11-character prefix, so its output differs from `redact()`.

## 8. Logging rules

1. Never log prompt or completion text. `llm_calls` holds metadata only
   (`test_llm_calls_never_store_prompt_text`).
2. `detect_injection()` returns rule ids, never matched text, so its output is safe to persist
   (`test_injection_matches_hold_rule_ids_not_text`); `confidence_signals` stores the score and counts.
3. Span logs go through `observability._scrub`: text-bearing attributes are replaced with `[omitted]`
   and other strings are redacted.
4. `confidence_signals.pii_redactions` stores the number of redactions per record, not the values.
5. Exception: validator error messages can carry `input_value=` excerpts of model output into
   `llm_calls.error` (risk R-06).

## 9. Re-running the measurements

Re-run section 6 after any change to `redact()` rules, after a large ingestion, or before a release, and
update the tables with the new date. `measure_corpus(limit=N)` runs on the first N complaints for a quick
check.
