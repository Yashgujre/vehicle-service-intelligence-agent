# Datasheet: VSIA NHTSA complaint and recall corpus

This datasheet follows the question set of Gebru et al., "Datasheets for Datasets" (Communications of the
ACM, 2021): motivation, composition, collection process, preprocessing, uses, distribution and
maintenance. It covers the corpus VSIA builds from public NHTSA data: owner complaints, recall campaigns
and recall documents. The labelled evaluation subset has its own datasheet:
[datasheet-gold-set.md](datasheet-gold-set.md).

All counts are from read-only queries on `data/vsia.db`, `data/docs/manifest.json` and
`data/index/*/info.json` on 2026-10-19, unless another source is named.

## Motivation

**For what purpose was the dataset created?**
To build and evaluate defect intelligence for vehicle quality and service teams: triage of owner
complaints into a component and severity, matching to known recalls, retrieval for question answering,
and weekly complaint-volume forecasting with spike alerts (PRD FR-1 to FR-9). Public NHTSA data is used
so that the whole system can be published and reproduced without access to any company's warranty or
service records.

**Who created it, and who funded it?**
It was assembled by the project author as an open-source portfolio project, with no funding. The
underlying records are created by vehicle owners (complaints) and manufacturers (recall reports), and
published by the U.S. National Highway Traffic Safety Administration (NHTSA).

## Composition

**What do the instances represent?**

| Instance type | Table or file | Count | Unit |
|---|---|---|---|
| Owner complaint | `complaints` | 10,303 | one NHTSA ODI complaint number |
| Recall x vehicle | `recalls` | 407 rows, 200 distinct campaigns | one campaign for one make, model and model year |
| Recall document | `recall_documents` | 150 documents for 80 campaigns | one parsed PDF: 80 Part 573 Safety Recall Reports (`RCLRPT`), 70 owner notification letters (`RCONL`) |
| Index record | `data/index/recalls`, `recall_docs` | 407 and 352 records | one recall row, one 800-token document chunk |

The complaints index namespace was being built at the time of writing and is not counted here.

**Is it a sample?** Yes. It is the complete set of NHTSA complaints returned by the public API for one
segment (ADR-0004): electric and hybrid SUVs and pickups from 8 makes, model years 2021 to 2026, filed on
or after 2022-01-01. Inside that segment the API result is taken in full; the segment itself is a
deliberate selection, not a random sample of the U.S. fleet.

**Complaints by make**

| Make | Complaints | Share |
|---|---|---|
| TESLA | 3,643 | 35.4% |
| FORD | 2,129 | 20.7% |
| HYUNDAI | 1,735 | 16.8% |
| VOLKSWAGEN | 994 | 9.6% |
| KIA | 796 | 7.7% |
| CHEVROLET | 427 | 4.1% |
| RIVIAN | 299 | 2.9% |
| TOYOTA | 280 | 2.7% |

**Complaints by model** (24 canonical model strings)

| Make | Model | Complaints |
|---|---|---|
| TESLA | MODEL Y | 3,433 |
| HYUNDAI | IONIQ 5 | 1,341 |
| VOLKSWAGEN | ID.4 | 994 |
| FORD | MAVERICK HYBRID | 690 |
| FORD | MUSTANG MACH E | 665 |
| KIA | EV6 | 547 |
| HYUNDAI | TUCSON HYBRID | 365 |
| FORD | F-150 HYBRID | 310 |
| CHEVROLET | EQUINOX EV | 282 |
| KIA | EV9 | 249 |
| FORD | F-150 LIGHTNING BEV | 240 |
| TESLA | CYBERTRUCK | 210 |
| TOYOTA | RAV4 PRIME | 204 |
| RIVIAN | R1S | 166 |
| RIVIAN | R1T | 133 |
| FORD | ESCAPE PHEV | 126 |
| CHEVROLET | BLAZER EV | 99 |
| FORD | ESCAPE HYBRID | 97 |
| TOYOTA | RAV4 HYBRID | 63 |
| CHEVROLET | SILVERADO EV | 46 |
| HYUNDAI | IONIQ 5 N | 18 |
| TOYOTA | RAV4 PLUG-IN HYBRID | 13 |
| HYUNDAI | TUCSON PLUG-IN HYBRID | 11 |
| FORD | F-150 LIGHTNING | 1 |

**Complaints by model year:** 2021: 1,736; 2022: 2,965; 2023: 2,844; 2024: 1,572; 2025: 1,011;
2026: 175.

**Complaints by year filed:** 2022: 1,338; 2023: 2,079; 2024: 2,161; 2025: 2,287; 2026 (to 2026-10-15):
2,438. First filing 2022-01-02, last 2026-10-15.

**What data does each complaint consist of?** NHTSA fields: ODI number, make, model, model year,
manufacturer, filing date, incident date, crash and fire flags, injury and death counts, the VIN as
published, NHTSA's component coding, and the owner's free-text narrative. Column definitions are in the
[data dictionary](data-dictionary.md#complaints).

- Narrative length: 7 to 2,830 characters, median 543, mean 684.
- Safety flags: 791 complaints report a crash, 66 a fire, 324 at least one injury, 14 at least one death;
  930 (9.0%) carry at least one of these flags (ADR-0062).
- `vin_prefix`: 10,242 rows hold 11 characters, 1 row holds 9, 60 are null. NHTSA does not publish full
  VINs.
- Every row has a narrative and an incident date.

**Is there a label or target?** NHTSA's own component coding (`components_raw`) is present on every
complaint. It is multi-label: 4,473 complaints (43.4%) list more than one component. VSIA maps it to a
24-value taxonomy (23 components plus `OTHER`) as `component_primary` (ADR-0005). Distribution of
`component_primary`:

| Component | Complaints | Component | Complaints |
|---|---|---|---|
| ELECTRICAL SYSTEM | 3,023 | ENGINE | 204 |
| FORWARD COLLISION AVOIDANCE | 1,201 | EXTERIOR LIGHTING | 193 |
| POWER TRAIN | 1,061 | LANE DEPARTURE | 160 |
| OTHER | 796 | FUEL/PROPULSION SYSTEM | 131 |
| VEHICLE SPEED CONTROL | 658 | BACK OVER PREVENTION | 120 |
| SERVICE BRAKES | 622 | SEAT BELTS | 105 |
| STEERING | 609 | WHEELS | 77 |
| VISIBILITY/WIPER | 415 | TIRES | 70 |
| STRUCTURE | 273 | SEATS | 63 |
| SUSPENSION | 272 | LATCHES/LOCKS/LINKAGES | 22 |
| AIR BAGS | 214 | PARKING BRAKE | 10 |
| | | HYBRID PROPULSION SYSTEM | 3 |
| | | ELECTRONIC STABILITY CONTROL | 1 |

This coding is used as ground truth for evaluation and as training labels for the baseline classifier. It
is never given to the LLM (ADR-0005). There are no severity labels and no complaint-to-recall links in the
source; those are derived as silver labels in the gold set.

**Recalls**

| Make | Rows | Campaigns |
|---|---|---|
| TESLA | 92 | 50 |
| FORD | 81 | 39 |
| RIVIAN | 81 | 23 |
| VOLKSWAGEN | 45 | 26 |
| HYUNDAI | 35 | 18 |
| CHEVROLET | 28 | 19 |
| KIA | 24 | 14 |
| TOYOTA | 21 | 11 |

- Report dates 2020-11-12 to 2026-10-07. Over-the-air remedy rows: 60; park-outside advisories: 12;
  park-it advisories: 1.
- Campaigns by primary component (a campaign can count under one component only): ELECTRICAL SYSTEM 56,
  EXTERIOR LIGHTING 16, SEAT BELTS 15, BACK OVER PREVENTION 14, SUSPENSION 12, POWER TRAIN 9,
  STRUCTURE 9, AIR BAGS 8, SERVICE BRAKES 8, VISIBILITY/WIPER 8, FORWARD COLLISION AVOIDANCE 7, OTHER 6,
  PARKING BRAKE 5, SEATS 5, ELECTRONIC STABILITY CONTROL 4, STEERING 4, TIRES 4, VEHICLE SPEED CONTROL 4,
  WHEELS 3, LATCHES/LOCKS/LINKAGES 2, ENGINE 1.

**Recall documents**

| Document type | Documents | Pages | Parser | Extraction method | Valid extractions |
|---|---|---|---|---|---|
| Part 573 report (`RCLRPT`) | 80 | 328 | 80 `pypdf` | 80 `rules` | 80 |
| Owner letter (`RCONL`) | 70 | 153 | 60 `pypdf`, 10 `pypdf+tesseract` | 8 `rules`, 62 `covered_by_part573` | 8 |
| Total | 150 | 481 | | 0 `llm` | 88 |

The 150 PDFs total 33,171,079 bytes (`manifest.json`). The fetch log records 80 campaigns selected
across 21 components. Owner letters marked `covered_by_part573` are kept for retrieval; their fields come
from the campaign's Part 573 report (ADR-0032).

**Is any information missing?** 60 complaints have no `vin_prefix`. Recall rows have no load timestamp.
120 of the 200 campaigns have no parsed document (only 80 were fetched, ADR-0031). Some hybrid owners file
under the non-hybrid model name (for example plain RAV4), so the segment under-counts hybrids (ADR-0004).

**Are there relationships between instances?** Complaints and recalls share make, model family and model
year; the agent links them through `recall_lookup` and retrieval. Recall model strings differ from
complaint model strings, so VSIA normalises both to a model family (`vsia.retrieval.model_family`).
Documents belong to a campaign through `campaign_number` taken from the fetch manifest.

**Are there recommended splits?** Yes, for the labelled subset: `splits-v1` (gold 200, calibration 300,
train 9,803), described in the [gold set datasheet](datasheet-gold-set.md). The forecast uses a time split
(12-week holdout, 3 rolling validation folds; `pipelines/forecast.py`).

**Are there errors, noise or redundancies?**
- Complaints are unverified owner reports; NHTSA codes components from the narrative, and the coding is
  not always the root cause.
- Several model strings name the same vehicle (`F-150 LIGHTNING` with 1 complaint and
  `F-150 LIGHTNING BEV` with 240; `RAV4 PRIME` and `RAV4 PLUG-IN HYBRID`).
- `OTHER` (796) is assigned when NHTSA lists no specific component (for example `UNKNOWN OR OTHER` only),
  so it is a heterogeneous class.

**Is the dataset self-contained?** No. It is a local copy of public NHTSA data. The ODI number and
campaign number link every row back to nhtsa.gov.

**Does it contain confidential data?** No. All records are published by NHTSA.

**Does it contain personal data?** Possibly, in free text. Owner narratives are written by members of the
public and can contain names, phone numbers, addresses, plates or dealer staff names despite NHTSA's own
review. Owner notification letters contain sample names and addresses; Part 573 reports contain company
contact names and phone numbers. The incident date and partial VIN are quasi-identifiers. VSIA stores the
narrative as received and redacts it with `vsia.guardrails.redact()` before any model, embedding, log or
published file ([data flow](../architecture/data-flow.md#redaction-points)). Recall document markdown is
redacted before storage; the ADR-0031 parse run applied 799 redactions.

**Does it relate to people?** Indirectly: complaints describe events experienced by drivers and
passengers, including injuries (324 complaints) and deaths (14 complaints). It contains no demographic
attributes.

## Collection process

**How was the data acquired?** Through NHTSA's public HTTPS APIs (`vsia.nhtsa`, `vsia.ingest`):

1. `/products/vehicle/models` resolves the model strings for the segment patterns in
   `config/settings.yaml`; the result (145 make, model and year entries) is cached in
   `data/raw/scoped_vehicles.json`.
2. `/complaints/complaintsByVehicle` is called once per entry; `/recalls/recallsByVehicle` once per
   distinct make, model and year found in the complaints plus the resolved strings.
3. Recall PDFs come from the unofficial `/safetyIssues/byNhtsaId` endpoint and `static.nhtsa.gov`
   (`scripts/fetch_recall_docs.py`): the latest Part 573 report and the earliest owner letter under 1 MB
   per campaign, with a 3 MB cap, throttled to about 3 requests per second.

**Sampling strategy.** Complete API results for the segment; recall documents for 80 campaigns chosen by
complaint volume, round-robin across components so that small components are represented.

**Time frame.** All loads ran on 2026-10-19 (UTC):

| Run | Kind | Window (UTC) | Fetched | Inserted | Duplicates | Filtered |
|---|---|---|---|---|---|---|
| 1 | complaints | 05:22:29 to 05:29:58 | 14,186 | 10,645 | 3,064 | 477 |
| 2 | recalls | 05:38:23 to 05:39:09 | 407 | 189 | 218 | 0 |
| 3 | complaints (re-run) | 05:39:09 to 05:39:49 | 14,186 | 0 | 13,367 | 819 |

The duplicates in run 1 are the same complaint returned for more than one model string. 342 rows inserted
by run 1 were removed afterwards under the `exclude_models` rule (plain `ESCAPE`, `ROBOTAXI (MODEL Y)`),
leaving 10,303; see [lineage gaps](lineage.md#known-lineage-gaps). The recall table's 218 duplicates show
an earlier recall load that has no run record.

**Who was involved?** No crowdworkers or annotators. Data collection is automated.

**Ethical review.** No formal ethical review was carried out; the data is public. The project's own controls are PII
redaction, no publication of raw narratives (the public dashboard shows a redacted snapshot, ADR-0072)
and no attempt to re-identify complainants.

**Were the individuals notified or did they consent?** NHTSA publishes complaints as public records; VSIA
does not contact complainants and adds no data about them.

## Preprocessing, cleaning and labelling

- **Normalisation** (`vsia.nhtsa.normalize_complaint`, `normalize_recall`): upper-case make; canonical
  model from the complaint's own product record (ADR-0004 point 3); ISO dates (recall dates arrive as
  DD/MM/YYYY); stripped narrative.
- **Filtering** at load: empty narrative, model in `exclude_models`, filed before 2022-01-01.
- **Derived label:** `component_primary` is the first specific canonical component in `components_raw`;
  `OTHER` only when nothing specific is listed (ADR-0005). This rule reduced `OTHER` from 1,030 to 796.
- **Documents:** pypdf text extraction, tesseract OCR when a PDF yields under 200 characters, page
  markers, redaction, then rules-first field extraction (ADR-0031, ADR-0032).
- **Index records:** recall text per campaign and vehicle; 800-token chunks with 100-token overlap for
  documents; redacted narrative only for complaints; every record carries `vehicle_keys`
  `MAKE|MODELFAMILY|YEAR` (ADR-0033).
- **Raw data saved?** The API responses are not stored separately; the database is the raw copy. The PDFs
  are kept in `data/docs/pdf/` with SHA-256 hashes.

## Uses

**Used for:** complaint triage and evaluation (FR-4, FR-12), recall matching and retrieval (FR-3), RAG
chat (FR-9), weekly complaint forecasting and spike detection (FR-7), and the dashboard (FR-8).

**Should not be used for:**
- Estimating defect rates or comparing the reliability of makes. Complaint counts depend on fleet size,
  owner engagement, media attention and NHTSA model naming; the corpus has no sales or fleet denominators.
- Any decision about an individual vehicle owner or complainant.
- Legal or regulatory conclusions about a defect. Complaints are unverified.
- Training models that output narrative text verbatim, which could reproduce residual PII.

**Known biases that affect use:** Tesla Model Y alone is 33.3% of complaints; component labels are
dominated by ELECTRICAL SYSTEM (29.3%); the 2026 model year has only 175 complaints; recent model years
and recent weeks are under-reported because complaints arrive with a lag; filing volume grows every year
(1,338 in 2022 to 2,438 in the first nine and a half months of 2026), which the forecast must treat as
trend rather than defect signal.

## Distribution

- The corpus is not redistributed. `data/*.db`, `data/docs/`, `data/index/` and `data/models/` are
  git-ignored; anyone can rebuild the corpus from the public APIs with `vsia ingest`,
  `scripts/fetch_recall_docs.py`, `python -m vsia.documents` and `scripts/build_index.py`.
- The public dashboard ships a redacted parquet snapshot in `app/demo_data/` (152,565 bytes, exported
  2026-10-19 06:12 UTC; ADR-0072).
- Source terms: the data is published by NHTSA on nhtsa.gov and its public APIs. Check NHTSA's current
  terms before republishing narratives.

## Maintenance

- **Owner:** the project author (see AGENTS.md for the workstream owners of each table).
- **Updates:** n8n workflow 01 runs the API ingestion daily at 06:00; loads are append-only and idempotent
  (existing ODI numbers and recall keys are skipped). NHTSA corrections to an existing complaint are not
  picked up, because existing rows are never overwritten.
- **Recall documents and index** are refreshed manually.
- **Versioning:** there is no dataset version number. A snapshot is identified by the `ingestion_runs`
  rows, the manifest SHA-256 hashes and the `info.json` timestamps ([lineage](lineage.md)).
- **Errata:** open an issue in the project repository.
