# 02 Technical Verification (as of 2026-10-18)

Scope: verify the current facts behind the Vehicle Service Intelligence Agent stack (Python 3.11, n8n, Postgres, Pinecone, LlamaParse, Claude / OpenAI / Ollama, MLflow, Streamlit, Open WebUI, Terraform on Oracle Cloud Always Free, Docker Compose).

Method: each fact below was checked on 2026-10-18 against official documentation, package registries, or a live call to the public endpoint. Status labels:

- **Verified (live)**: confirmed by calling the endpoint or installing the package today.
- **Verified (docs)**: confirmed on the official documentation page cited.
- **Unverified**: not confirmed from an official source; treat as an assumption.

A "PRD discrepancy" note appears wherever the PRD assumption (as phrased in the research request) is wrong or outdated.

---

## 1. NHTSA APIs

### 1.1 Endpoints (Verified, live)

Base URL: `https://api.nhtsa.gov`. No API key. Responses are JSON. Parameter **names are case-sensitive** (`modelYear=` works, `modelyear=` returns HTTP 400). Parameter **values are case-insensitive** (`mustang mach-e` returns the same 139 rows as `MUSTANG MACH-E`).

| Purpose | Request |
| --- | --- |
| Model years with complaints | `GET /products/vehicle/modelYears?issueType=c` |
| Makes for a year | `GET /products/vehicle/makes?modelYear=2023&issueType=c` |
| Models for a make and year | `GET /products/vehicle/models?modelYear=2023&make=TESLA&issueType=c` |
| Complaints by vehicle | `GET /complaints/complaintsByVehicle?make=FORD&model=MUSTANG%20MACH-E&modelYear=2022` |
| Complaint by ODI number | `GET /complaints/odinumber?odinumber=11770375` |
| Same three product endpoints for recalls | replace `issueType=c` with `issueType=r` |
| Recalls by vehicle | `GET /recalls/recallsByVehicle?make=FORD&model=MUSTANG%20MACH%20E&modelYear=2022` |
| Recalls by campaign number | `GET /recalls/campaignNumber?campaignNumber=22V412000` |
| Recall with document links (undocumented, used by nhtsa.gov) | `GET /safetyIssues/byNhtsaId?filter=recalls&nhtsaId=22V412000` |

Copy-paste test:

```bash
curl -s -G "https://api.nhtsa.gov/complaints/complaintsByVehicle" \
  --data-urlencode "make=FORD" --data-urlencode "model=MUSTANG MACH-E" --data-urlencode "modelYear=2022"
curl -s -G "https://api.nhtsa.gov/recalls/recallsByVehicle" \
  --data-urlencode "make=FORD" --data-urlencode "model=MUSTANG MACH E" --data-urlencode "modelYear=2022"
curl -s "https://api.nhtsa.gov/safetyIssues/byNhtsaId?filter=recalls&nhtsaId=22V412000"
```

Source: https://www.nhtsa.gov/nhtsa-datasets-and-apis (official syntax for every endpoint except `safetyIssues`, which was found and verified live).

### 1.2 Response shapes and quirks (Verified, live)

- **Complaints** response: `{"count", "message", "results":[...]}` (lowercase keys). Each result has `odiNumber`, `manufacturer`, `crash`, `fire`, `numberOfInjuries`, `numberOfDeaths`, `dateOfIncident` and `dateComplaintFiled` (both `MM/DD/YYYY`), `vin` (first 11 characters only), `components` (comma-separated string), `summary`, and `products[]` (`productYear`, `productMake`, `productModel`, `type`).
- **Recalls** response: `{"Count", "Message", "results":[...]}` (capitalized keys). Each result has `Manufacturer`, `NHTSACampaignNumber`, `parkIt`, `parkOutSide`, `overTheAirUpdate`, `ReportReceivedDate` (**`DD/MM/YYYY`**, for example `16/02/2022`), `Component`, `Summary`, `Consequence`, `Remedy`, `Notes`, `ModelYear`, `Make`, `Model`. The campaign-number endpoint adds `PotentialNumberofUnitsAffected` and returns one row per affected make/model/year.
- **No match returns HTTP 400**, not 404 or 200. `recallsByVehicle` with an unknown model string returns `HTTP 400` and body `{"Count":0,"Message":"Results returned successfully","results":[]}`. The same happens when a valid model simply has no recalls (for example KIA EV6 2025). Treat 400 plus `Count == 0` as "empty", not as an error. Unknown campaign numbers return HTTP 200 with `Count: 0`.
- **Complaint and recall model strings differ.** The recall API normalizes names differently from the complaint API, even when the string comes from the `issueType=r` model list. Example: the recall model list for Ford 2022 includes `MUSTANG MACH-E`, but `recallsByVehicle` returns 400 for it; `MUSTANG MACH E` (no hyphen, the spelling used in complaint `products[].productModel`) returns 9 recalls.
- **Complaint model strings are exact per model year.** `MUSTANG MACH-E` works for 2022 but returns 400 for 2023, where the string is `MUSTANG MACH-E BEV`. Plain `MODEL Y` returns 400 for 2022 to 2024 and only works for 2025.
- **Variant strings overlap.** Tesla `MODEL Y  5-SEAT` (two spaces) and `MODEL Y 7-SEAT` for 2022 return the identical 870 complaints. For 2023, `MODEL Y RWD EARLY RELEASE` (78) is a subset of `MODEL Y (All Variants)` (1181). **Deduplicate on `odiNumber`** when pulling several variants.
- The Ford `MUSTANG` recall query returns gasoline Mustang recalls only; Mach-E recalls are filed under `MUSTANG MACH E`.
- RAV4 hybrid complaints are thin under `RAV4 HYBRID` (1 to 8 per year); many hybrid owners file under `RAV4`. Pull both and classify the powertrain from the complaint text.
- Complaint data is live. A complaint filed 10/11/2026 (ODI 11770375) was already returned today.

### 1.3 Working model strings, 2022 to 2025 (Verified, live, 2026-10-18)

Full table saved as `data/raw/nhtsa_model_strings.json` (52 rows: `make`, `model`, `modelYear`, `complaint_count`, plus `recall_model_string` and `recall_count`). `model` is the complaint-API string. Counts are as of today and will grow.

| Make | Year | Complaint model string | Complaints | Recall model string | Recalls |
| --- | --- | --- | --- | --- | --- |
| FORD | 2022 | `F-150 (Super Crew) Lightning BEV` | 307 | `F-150 LIGHTNING BEV` | 9 |
| FORD | 2022 | `MUSTANG MACH-E` | 139 | `MUSTANG MACH E` | 9 |
| FORD | 2023 | `F-150 (SUPER CREW) LIGHTNING BEV` | 206 | `F-150 LIGHTNING BEV` | 9 |
| FORD | 2023 | `MUSTANG MACH-E BEV` | 126 | `MUSTANG MACH E` | 6 |
| FORD | 2024 | `F-150 (SUPER CREW) LIGHTNING BEV` | 30 | `F-150 LIGHTNING BEV` | 4 |
| FORD | 2024 | `MUSTANG MACH-E BEV` | 47 | `MUSTANG MACH E` | 5 |
| FORD | 2025 | `F-150 (SUPER CREW) LIGHTNING BEV` | 8 | `F-150 LIGHTNING BEV` | 3 |
| FORD | 2025 | `MUSTANG MACH-E BEV` | 14 | `MUSTANG MACH E` | 7 |
| RIVIAN | 2022 | `R1S` / `R1T` | 4 / 70 | `R1S` / `R1T` | 13 / 12 |
| RIVIAN | 2023 | `R1S` / `R1T` | 76 / 40 | `R1S` / `R1T` | 10 / 8 |
| RIVIAN | 2024 | `R1S` / `R1T` | 17 / 10 | `R1S` / `R1T` | 7 / 7 |
| RIVIAN | 2025 | `R1S` / `R1T` | 55 / 10 | `R1S` / `R1T` | 11 / 8 |
| TESLA | 2022 | `MODEL Y  5-SEAT` (two spaces) or `MODEL Y 7-SEAT` (same set) | 870 | `MODEL Y` | 20 |
| TESLA | 2023 | `MODEL Y (All Variants)` (superset of the RWD / LATER RELEASE strings) | 1181 | `MODEL Y` | 17 |
| TESLA | 2024 | `MODEL Y (All Variants)`; `MODEL Y RWD` | 328; 34 | `MODEL Y` | 5 |
| TESLA | 2025 | `MODEL Y` | 106 | `MODEL Y` | 3 |
| HYUNDAI | 2022 / 2023 / 2024 / 2025 | `IONIQ 5` | 407 / 388 / 224 / 297 | `IONIQ 5` | 3 / 4 / 3 / 9 |
| HYUNDAI | 2025 | `IONIQ 5 N` | 18 | (no recalls; API returns 400) | 0 |
| KIA | 2022 / 2023 / 2024 / 2025 | `EV6` | 278 / 137 / 77 / 55 | `EV6` | 4 / 4 / 3 / 0 |
| CHEVROLET | 2024 / 2025 | `SILVERADO EV` | 25 / 14 | `SILVERADO EV` | 4 / 1 |
| CHEVROLET | 2024 / 2025 | `BLAZER EV` | 78 / 21 | `BLAZER EV` | 5 / 3 |
| CHEVROLET | 2024 / 2025 | `EQUINOX EV` | 108 / 163 | `EQUINOX EV` | 1 / 6 |
| TOYOTA | 2022 to 2025 | `RAV4` | 149 / 159 / 176 / 90 | `RAV4` | 1 / 3 / 3 / 3 |
| TOYOTA | 2022 to 2025 | `RAV4 HYBRID` | 5 / 8 / 1 / 5 | `RAV4 HYBRID` | 2 / 1 / 2 / 2 |
| TOYOTA | 2022 to 2024 | `RAV4 PRIME` | 22 / 65 / 29 | `RAV4 PRIME` | 3 / 2 / 2 |
| TOYOTA | 2025 | `RAV4 PHEV` | 10 | `RAV4 PLUG-IN HYBRID` | 2 |

Chevrolet Silverado EV, Blazer EV and Equinox EV have no 2022 or 2023 entries (their first model year is 2024).

Recommended ingestion pattern: always discover strings at run time with `/products/vehicle/models?...&issueType=c`, filter by regex, then query each string and deduplicate on `odiNumber`. For recalls, try the `issueType=r` string first, and on HTTP 400 fall back to the complaint `products[].productModel` spelling, or skip the vehicle API and use the flat file `FLAT_RCL_POST_2010.zip` (field `MODELTXT`).

### 1.4 Recall document PDFs (Verified, live)

- `recallsByVehicle` and `campaignNumber` **do not return document links** (checked all keys).
- `GET https://api.nhtsa.gov/safetyIssues/byNhtsaId?filter=recalls&nhtsaId=22V412000` returns `results[0].recalls[0].associatedDocuments[]`, each with `fileName`, `fileSize`, `loadDate`, `mimeType`, `summary`, and a direct `url`. Recall 22V412 (Mach-E high-voltage contactor) lists 26 documents. Both `22V412000` and `22V412` are accepted. The same object also carries `subject`, `mfrCampaignNumber`, `potentialNumberOfUnitsAffected`, `components[]`, and ISO-8601 dates. This endpoint is **not on the official API page**, so treat it as unofficial and possibly unstable.
- URL pattern: `https://static.nhtsa.gov/odi/rcl/{YYYY}/{PREFIX}-{CAMPAIGN6}-{DOCID}.{PDF|pdf}`, where `YYYY` is the campaign year, `CAMPAIGN6` is the campaign number without the trailing `000` (for example `22V412`), and `DOCID` is a 4-digit document id that **cannot be predicted**. Get it from `associatedDocuments`. File-extension case varies (`.PDF` for RCLRPT and RCLQRT, `.pdf` for others). Example (HTTP 200, `application/pdf`, 222,185 bytes): `https://static.nhtsa.gov/odi/rcl/2022/RCLRPT-22V412-2331.PDF`.
- Prefixes observed: `RCLRPT` (Part 573 defect report), `RCAK` (recall acknowledgement), `RCMN` (manufacturer notices to dealers, the closest thing to a service bulletin for the recall), `RCONL` (owner notification letter, Part 577), `RCRN` (renotification), `RCLQRT` (quarterly report), `RCLYLY` (annual report), `RMISC` (miscellaneous, for example OTA messaging).

### 1.5 Flat files (Verified, live HEAD requests plus official page)

All are tab-delimited, dates `YYYYMMDD`, updated daily. Base: `https://static.nhtsa.gov/odi/ffdd/`.

| Dataset | Zip (size on 2026-10-18) | Layout file |
| --- | --- | --- |
| Complaints (all) | `cmpl/FLAT_CMPL.zip` (357 MB) | `cmpl/CMPL.txt` (51 fields; fields 50 to 51, State of Incident and Vehicle Operator, added 2026-04-30) |
| Complaints, 5-year slices | `cmpl/COMPLAINTS_RECEIVED_2025-2026.zip` (40 MB), `..._2020-2024.zip` (72 MB), etc. | `cmpl/CMPL.txt` |
| Recalls | `rcl/FLAT_RCL_POST_2010.zip` (14 MB), `rcl/FLAT_RCL_PRE_2010.zip` (7 MB), plus `FLAT_RCL_Qrtly_Rpts.zip`, `FLAT_RCL_Annual_Rpts.zip`, `RCL_FROM_2020_2024.zip`, etc. | `rcl/RCL.txt` (29 fields; 28 and 29 are DO_NOT_DRIVE and PARK_OUTSIDE, added May 2025) |
| Investigations | `inv/FLAT_INV.zip` (4 MB) | `inv/INV.txt` (11 fields; `CAMPNO` links to recalls) |
| TSBs / manufacturer communications | `tsbs/TSBS_RECEIVED_2025-2026.zip` (12 MB), `tsbs/TSBS_RECEIVED_2020-2024.zip` (30 MB), and CSV variants `tsbs/MFR_COMMS_RECEIVED_<range>.zip` | `tsbs/TSBS.txt` |

PRD discrepancy (flat files):
- `FLAT_RCL.zip` returns 404; recalls are split into `FLAT_RCL_POST_2010.zip` and `FLAT_RCL_PRE_2010.zip`.
- There is **no single `FLAT_TSBS.zip`** (404). TSBs come in 5-year files, `TSBS_RECEIVED_<range>.zip` (TSV, full fields) and `MFR_COMMS_RECEIVED_<range>.zip` (CSV, one row per document and product, with a concise summary). The layout file `TSBS.txt` says the dataset was renamed "Manufacturer Communications" in May 2024. Its fields include "TSB/Document ID", "Communication Type" (Service Bulletin, Service Campaign, Warranty Program, Over The Air, Emissions, Other), and "Summary" (up to 4000 characters since June 2024). The TSB flat file has metadata and summaries, **not TSB PDFs**.

### 1.6 Rate limits

- Verified (docs): NHTSA publishes **no numeric limit** for `api.nhtsa.gov`. The API Use Policy (https://api.nhtsa.gov/, last updated January 2023) says the API serves NHTSA.gov and that bulk VIN lookups "will be controlled by an automated traffic rate control mechanism". vPIC's FAQ (https://vpic.nhtsa.dot.gov/api/Home/Index/FAQ) cites 1,000 to 2,000 transactions per minute of capacity and asks for large batches at night or on weekends; that guidance is for vPIC, not the complaints and recalls API.
- Verified (live): no rate-limit headers are returned (responses come through AWS API Gateway). 40 back-to-back calls in 3 seconds all returned 200.
- Recommendation: throttle to about 2 to 5 requests per second with retry and backoff on 429 and 5xx, and use the flat files for bulk history.

PRD discrepancy (NHTSA):
- The Tesla 2023 complaint string `MODEL Y (All Variants)` is correct (the PRD guess holds), but it is **year-specific**: 2022 uses `MODEL Y  5-SEAT` / `MODEL Y 7-SEAT`, and 2025 uses `MODEL Y`.
- `MUSTANG MACH-E` works for complaints only for 2021 and 2022; 2023 to 2025 use `MUSTANG MACH-E BEV`.
- The complaint strings `MUSTANG MACH-E` and `F-150 (SUPER CREW) LIGHTNING BEV` **do not work for recalls** (HTTP 400). Use `MUSTANG MACH E` and `F-150 LIGHTNING BEV`.
- No official recall API returns document links; only the unofficial `safetyIssues/byNhtsaId` does.

---

## 2. n8n

### 2.1 Versions (Verified, registry plus docs)

- `n8n` stable 2.43.7, beta/next 2.44.3 (npm dist-tags, and the docs page "Current stable: 2.43.7"). n8n 2.43.7 depends on `n8n-nodes-base` 2.43.5 and `@n8n/n8n-nodes-langchain` 2.43.5; the type versions below come from those exact packages.
- Docker image: `n8nio/n8n` (also `docker.n8n.io/n8nio/n8n`), port `5678`, data volume `/home/node/.n8n`. Tag `2.43.7` is multi-arch (`amd64`, `arm64`), so it runs on the OCI A1 ARM VM. Pin a version tag rather than `latest`.
- Source: https://docs.n8n.io/hosting/installation/docker/ (that page now points to "Install using Docker Compose" as the recommended method).

### 2.2 Node `type` strings and current (highest) `typeVersion` (Verified, from package source)

| Node (UI name) | `type` | Latest `typeVersion` | Available versions |
| --- | --- | --- | --- |
| Schedule Trigger | `n8n-nodes-base.scheduleTrigger` | 1.4 | 1, 1.1, 1.2, 1.3, 1.4 |
| Webhook | `n8n-nodes-base.webhook` | 2.2 | 1, 1.1, 2, 2.1, 2.2 |
| Respond to Webhook | `n8n-nodes-base.respondToWebhook` | 1.5 | 1 to 1.5 |
| HTTP Request | `n8n-nodes-base.httpRequest` | 4.5 | 1, 2, 3, 4, 4.1 to 4.5 |
| Postgres | `n8n-nodes-base.postgres` | 2.7 | 1, 2, 2.1 to 2.7 |
| Code | `n8n-nodes-base.code` | 2 | 1, 2 |
| If | `n8n-nodes-base.if` | 2.3 | 1, 2, 2.1, 2.2, 2.3 |
| Execute Workflow (UI: "Execute Sub-workflow") | `n8n-nodes-base.executeWorkflow` | 1.4 | 1 to 1.4 |
| Execute Workflow Trigger | `n8n-nodes-base.executeWorkflowTrigger` | 1.3 | 1 to 1.3 |
| AI Agent | `@n8n/n8n-nodes-langchain.agent` | 3.1 | 1 to 1.9, 2, 2.1, 3, 3.1 |
| Anthropic Chat Model | `@n8n/n8n-nodes-langchain.lmChatAnthropic` | 1.6 | 1 to 1.6 |
| OpenAI Chat Model | `@n8n/n8n-nodes-langchain.lmChatOpenAi` | 1.3 | 1 to 1.3 |
| Ollama Chat Model | `@n8n/n8n-nodes-langchain.lmChatOllama` | 1 | 1 |
| Call n8n Workflow Tool | `@n8n/n8n-nodes-langchain.toolWorkflow` | 2.2 | 1 to 1.3, 2, 2.1, 2.2 |
| HTTP Request Tool (legacy) | `@n8n/n8n-nodes-langchain.toolHttpRequest` | 1.1 | 1, 1.1 (`hidden: true`, no longer offered in the node picker) |
| HTTP Request as a tool (current) | `n8n-nodes-base.httpRequestTool` | 4.5 (assumed to track HTTP Request) | see note |
| Structured Output Parser | `@n8n/n8n-nodes-langchain.outputParserStructured` | 1.3 | 1 to 1.3 |

Note on the HTTP tool: the legacy `toolHttpRequest` node is hidden in 2.43.5, and its docs URL now redirects to the HTTP Request node page, which says to attach the HTTP Request node to an AI agent as a tool. The HTTP Request node declares `usableAsTool`, and n8n identifies tool variants by the `Tool` suffix (`node-helpers.js`), which gives `n8n-nodes-base.httpRequestTool`. **The exact `type` string and `typeVersion` of the tool variant are inferred, not read from source.** Confirm them by exporting one node from the running instance.

The Anthropic chat node's built-in model list includes ids up to `claude-sonnet-5`, `claude-opus-4-7` and `claude-haiku-4` prefixes. Set the model id by expression or "By ID" (for example `claude-haiku-5-5`) if the list lags behind the current models.

### 2.3 Workflow JSON format (Verified, from `n8n-workflow` 2.43.5 `interfaces.d.ts`)

Export / import top-level keys (`IWorkflowBase`): `name`, `nodes[]`, `connections{}`, `settings{}`, `staticData`, `pinData{}`, `meta{}`, `versionId`, `active`, `id`, `tags[]`, plus server-managed fields (`isArchived`, `createdAt`, `updatedAt`, `activeVersionId`, `versionCounter`, `nodeGroups`). For import, `name`, `nodes`, `connections` and `settings` are enough.

Node object (`INode`): required `id` (UUID), `name` (unique in the workflow; connections refer to it), `type`, `typeVersion` (number), `position` (`[x, y]`), `parameters` (object). Optional: `credentials` (`{"<credType>": {"id": "...", "name": "..."}}`), `webhookId`, `disabled`, `notes`, `notesInFlow`, `retryOnFail`, `maxTries`, `waitBetweenTries`, `alwaysOutputData`, `executeOnce`, `onError` (`stopWorkflow` | `continueRegularOutput` | `continueErrorOutput`), `continueOnFail`.

Connections are keyed by **source node name**, then connection type, then output index, then a list of targets:

```json
{
  "name": "nhtsa-ingest",
  "nodes": [
    {"id": "1f0c...", "name": "Schedule Trigger", "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.4, "position": [0, 0],
     "parameters": {"rule": {"interval": [{"field": "hours", "hoursInterval": 24}]}}},
    {"id": "2a9d...", "name": "Fetch Complaints", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.5, "position": [220, 0],
     "parameters": {"url": "https://api.nhtsa.gov/complaints/complaintsByVehicle", "sendQuery": true,
       "queryParameters": {"parameters": [{"name": "make", "value": "KIA"}, {"name": "model", "value": "EV6"}, {"name": "modelYear", "value": "2022"}]}}}
  ],
  "connections": {
    "Schedule Trigger": {"main": [[{"node": "Fetch Complaints", "type": "main", "index": 0}]]}
  },
  "settings": {"executionOrder": "v1"}
}
```

AI sub-node wiring uses the **sub-node as the source** and a non-`main` connection type: `"Anthropic Chat Model": {"ai_languageModel": [[{"node": "AI Agent", "type": "ai_languageModel", "index": 0}]]}`. Connection types: `main`, `ai_agent`, `ai_chain`, `ai_document`, `ai_embedding`, `ai_languageModel`, `ai_memory`, `ai_outputParser`, `ai_retriever`, `ai_reranker`, `ai_textSplitter`, `ai_tool`, `ai_vectorStore`.

The parameter shapes in the example (`rule.interval`, `queryParameters.parameters`) follow common exports but were not checked against each node's schema. Build one node in the UI and export it to confirm.

### 2.4 Self-host env vars (Verified, docs)

```env
DB_TYPE=postgresdb
DB_POSTGRESDB_HOST=postgres
DB_POSTGRESDB_PORT=5432
DB_POSTGRESDB_DATABASE=n8n
DB_POSTGRESDB_USER=n8n
DB_POSTGRESDB_PASSWORD=change-me
DB_POSTGRESDB_SCHEMA=public
N8N_ENCRYPTION_KEY=<32+ random chars; keep stable or saved credentials become unreadable>
N8N_HOST=n8n.example.com
N8N_PROTOCOL=https
N8N_WEBHOOK_URL=https://n8n.example.com/
GENERIC_TIMEZONE=America/Chicago
TZ=America/Chicago
N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=true
```

Sources: https://docs.n8n.io/hosting/installation/docker/, https://docs.n8n.io/hosting/configuration/environment-variables/deployment, https://docs.n8n.io/hosting/configuration/environment-variables/endpoints.

PRD discrepancy (n8n):
- `WEBHOOK_URL` is **deprecated since n8n 2.35.0**; use `N8N_WEBHOOK_URL` (the old name still works but logs a warning).
- `N8N_RUNNERS_ENABLED` is deprecated from 2.0 and no longer needed.
- The dedicated "HTTP Request Tool" node (`toolHttpRequest`) is legacy and hidden; use the HTTP Request node as a tool (`n8n-nodes-base.httpRequestTool`), or `toolWorkflow` to call a sub-workflow.
- Docs list `N8N_BLOCK_ENV_ACCESS_IN_NODE` default as `false`. Unverified whether the 2.x Docker image overrides it; if Code nodes need `$env`, set it explicitly.
- "Community Edition" has no separate image; the self-hosted Community Edition is the standard `n8nio/n8n` image without a license key.

---

## 3. Open WebUI

### 3.1 Version and image (Verified, GitHub plus docs)

- Latest release v0.12.3 (2026-10-16).
- Image `ghcr.io/open-webui/open-webui:main` (or pin `:v0.12.3`). The container listens on **8080**; the docs map it as `-p 3000:8080`. Data volume `/app/backend/data`. Set `WEBUI_SECRET_KEY`. The image is multi-arch (`amd64`, `arm64`).
- Docs quick start: `docker run -d -p 3000:8080 --add-host=host.docker.internal:host-gateway -v open-webui:/app/backend/data -e WEBUI_SECRET_KEY=your-secret-key --name open-webui --restart always ghcr.io/open-webui/open-webui:main`
- Docker Hub mirror `openwebui/open-webui` carries only a subset of tags; `:main` and `:vX.Y.Z` exist on ghcr.io only.
- Source: https://docs.openwebui.com/getting-started/quick-start

### 3.2 Pipe function interface (Verified, docs)

- `class Pipe:` with nested `class Valves(BaseModel)` (admin settings, reloaded from the database on every request) and optional `class UserValves(BaseModel)` (per user, arrives as `__user__["valves"]`).
- `def __init__(self): self.valves = self.Valves()`.
- `pipes` (method, async method, or plain list) returns `[{"id": "...", "name": "..."}]` to expose several models (a "manifold"). The model id becomes `<function_id>.<sub_id>`; strip the prefix with `body["model"].split(".", 1)[1]`. If any entry lacks `id` or `name`, the whole function is skipped.
- `async def pipe(self, body: dict, __user__: dict, __event_emitter__=None, ...)`. Special args are injected only if named: `__user__`, `__request__`, `__event_emitter__`, `__event_call__`, `__chat_id__`, `__session_id__`, `__message_id__`, `__task__`, `__task_body__`, `__files__`, `__metadata__`, `__oauth_token__`, `__tools__`. `__event_emitter__` is `None` for plain API calls.
- Return values: `str` (one chunk), sync or async generator (streamed; strings are wrapped as chat chunks; strings starting with `data:` pass through untouched), `dict`, or `StreamingResponse`. An exception that escapes `pipe()` is shown as an error on the message.
- Use `httpx.AsyncClient`, not `requests`, inside async methods (`requests` blocks the event loop). Extra pip packages go in the file's frontmatter docstring: `requirements: httpx`.
- If the pipe wraps a self-contained agent, **do not emit `delta.tool_calls`**, because that triggers Open WebUI's tool-execution retry loop. Render tool steps as `<details type="tool_calls" ...>` content blocks instead.

Event emitter payloads (Verified, docs):

```python
await __event_emitter__({"type": "status", "data": {"description": "Querying NHTSA...", "done": False}})
await __event_emitter__({"type": "source", "data": {
    "source": {"name": "NHTSA recall 22V412", "id": "22V412000"},
    "document": ["High Voltage Battery Contactor May Overheat"],
    "metadata": [{"source": "https://static.nhtsa.gov/odi/rcl/2022/RCLRPT-22V412-2331.PDF",
                  "name": "Part 573 report", "url": "https://static.nhtsa.gov/odi/rcl/2022/RCLRPT-22V412-2331.PDF"}]}})
await __event_emitter__({"type": "status", "data": {"description": "Done", "done": True}})
```

Minimal pipe that calls an n8n webhook and streams the answer (the pattern follows the docs' proxy example; adjust to the webhook's response format):

```python
"""
title: Vehicle Service Intelligence Agent
requirements: httpx
"""
from pydantic import BaseModel, Field
import httpx

class Pipe:
    class Valves(BaseModel):
        N8N_WEBHOOK_URL: str = Field(default="http://n8n:5678/webhook/vsia-chat")
        N8N_BEARER: str = Field(default="")
        TIMEOUT_S: int = Field(default=120)

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
        return [{"id": "vsia", "name": "Vehicle Service Intelligence"}]

    async def pipe(self, body: dict, __user__: dict, __event_emitter__=None):
        question = body["messages"][-1]["content"]
        if __event_emitter__:
            await __event_emitter__({"type": "status", "data": {"description": "Calling agent workflow", "done": False}})
        headers = {"Authorization": f"Bearer {self.valves.N8N_BEARER}"} if self.valves.N8N_BEARER else {}
        payload = {"question": question, "user_id": __user__.get("id"), "messages": body["messages"]}

        async def stream():
            async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_S) as client:
                async with client.stream("POST", self.valves.N8N_WEBHOOK_URL, json=payload, headers=headers) as r:
                    r.raise_for_status()
                    async for text in r.aiter_text():
                        yield text
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": "Done", "done": True}})

        if body.get("stream", False):
            return stream()
        async with httpx.AsyncClient(timeout=self.valves.TIMEOUT_S) as client:
            r = await client.post(self.valves.N8N_WEBHOOK_URL, json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
            return data.get("answer", str(data))
```

Unverified: whether the n8n Webhook / Respond to Webhook pair streams chunked output end to end. The safe default is non-streaming JSON (`{"answer": ..., "citations": [...]}`), emitting citations through `source` events.

Sources: https://docs.openwebui.com/features/extensibility/plugin/functions/pipe, https://docs.openwebui.com/features/extensibility/plugin/development/events

---

## 4. Pinecone

### 4.1 SDK (Verified, PyPI plus local install)

- Package **`pinecone`** 10.0.0 (released 2026-09-03), `Requires-Python >=3.10`. `pinecone-client` is deprecated (last release 6.0.0).
- Install with `pip install "pinecone==10.0.0"` (add the `[grpc]` extra only if needed).
- **In v10, data-plane methods are keyword-only.** `index.upsert_records("ns", [...])` (the positional form still shown in the docs) raises `PineconeValueError: Index.upsert_records() is a keyword-only method`.
- Signatures checked on the installed package:
  - `pc.create_index_for_model(name, cloud, region, embed, tags=None, deletion_protection='disabled', read_capacity=None, schema=None, timeout=None)`
  - `index.upsert_records(*, records, namespace, timeout=None)`
  - `index.search(*, namespace, top_k=None, inputs=None, vector=None, id=None, filter=None, fields=None, rerank=None, match_terms=None, query=None, timeout=None)` (`search_records` is an alias)

```python
import os
from pinecone import Pinecone

pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
INDEX = "vsia-docs"
if not pc.has_index(INDEX):
    pc.create_index_for_model(
        name=INDEX, cloud="aws", region="us-east-1",
        embed={"model": "llama-text-embed-v2", "field_map": {"text": "chunk_text"}},
    )
index = pc.Index(host=pc.describe_index(INDEX).host)

index.upsert_records(namespace="complaints", records=[
    {"_id": "cmpl-11770375-0", "chunk_text": "High voltage battery warning ...",
     "make": "FORD", "model": "MUSTANG MACH-E", "model_year": 2021, "component": "ELECTRICAL SYSTEM",
     "source_type": "complaint", "odi_number": 11770375},
])  # max 96 records per call for text records

res = index.search(
    namespace="complaints",
    query={"inputs": {"text": "HV battery contactor loss of drive power"}, "top_k": 8,
           "filter": {"$and": [{"make": {"$eq": "FORD"}}, {"model_year": {"$gte": 2021}}]}},
    fields=["chunk_text", "make", "model", "model_year", "odi_number"],
)
```

- Records: `_id` (or `id`), the `field_map` text field, and any other flat fields, which are stored as metadata and filterable. Namespaces are created on first upsert; `"__default__"` is the default namespace.
- Filter operators: `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte`, `$in`, `$nin`, `$exists`, `$and`, `$or`, `$not`. A bare value means `$eq` (`{"category": "digestive system"}`). Comparison operators cannot sit at the top level; nest them under a field.
- Hosted embedding models: `llama-text-embed-v2` (dimension 1024 default, also 2048, 768, 512, 384; max 2048 tokens) and `multilingual-e5-large` (1024, max 507 tokens). Integrated-embedding indexes do not support update or import with text.
- Batch limits: 96 records per call for text records; 1,000 records or 2 MB for vector records.

### 4.2 Starter (free) plan limits (Verified, docs)

| Limit | Starter |
| --- | --- |
| Projects per org | 1 |
| Users per org | 2 |
| Serverless indexes per project | 5 |
| Storage per org | 2 GB |
| Namespaces per index | 100 |
| Read units per month | 1,000,000 |
| Write units per month | 2,000,000 |
| Embedding tokens per month, per model | 5,000,000 |
| `llama-text-embed-v2` passage embedding rate | 250,000 tokens per minute |
| Region | AWS `us-east-1` only |

Sources: https://docs.pinecone.io/reference/api/database-limits/object-limits, https://docs.pinecone.io/reference/api/database-limits/rate-limits, https://docs.pinecone.io/guides/index-data/index-configuration

### 4.3 Terraform (Verified, registry plus provider docs)

- Provider `pinecone-io/pinecone` v5.0.0 (2026-10-12). Auth via the `PINECONE_API_KEY` environment variable.
- v5 introduced a `schema` + `deployment` style (Pinecone API version `2026-07`). The older `spec` + `embed` style is "planned for deprecation", but **integrated-embedding indexes still require the `spec` style**.

```hcl
terraform {
  required_providers {
    pinecone = { source = "pinecone-io/pinecone", version = "~> 5.0" }
  }
}
provider "pinecone" {}

resource "pinecone_index" "vsia" {
  name = "vsia-docs"
  spec = { serverless = { cloud = "aws", region = "us-east-1" } }
  embed = {
    model     = "llama-text-embed-v2"
    field_map = { text = "chunk_text" }
  }
}
```

Source: https://github.com/pinecone-io/terraform-provider-pinecone/blob/main/docs/resources/index.md

PRD discrepancy (Pinecone):
- Docs examples call `upsert_records(namespace, records)` positionally; with SDK 10.0.0 this fails. Always pass keywords.
- Pinecone's new API version is `2026-07` with document schemas and full-text search. Integrated embedding still uses `create_index_for_model`, and the Terraform `spec` style is still required for it.
- The Starter plan is AWS `us-east-1` only.

---

## 5. LlamaParse

### 5.1 REST API v2 (Verified, docs)

- Base URL: `https://api.cloud.llamaindex.ai`. Auth header: `Authorization: Bearer $LLAMA_CLOUD_API_KEY`.
- Upload and parse in one request (multipart): `POST /api/v2/parse/upload` with form fields `file` and `configuration` (a JSON string). The response has `id` and `status` at the top level.
- Job status and results: `GET /api/v2/parse/{job_id}?expand=markdown`. In this response the status is nested at `job.status` (values `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`). Markdown per page is at `markdown.pages[i].markdown`; `expand=markdown_full` returns one concatenated string. Other expand values: `text`, `items`, `metadata`, `job_metadata`, `usage`, `text_full`, plus `*_content_metadata` variants that return presigned download URLs.
- List jobs: `GET /api/v2/parse?page_size=10&status=COMPLETED`.

```bash
curl -X POST "https://api.cloud.llamaindex.ai/api/v2/parse/upload" \
  -H "Authorization: Bearer $LLAMA_CLOUD_API_KEY" \
  -F "file=@RCLRPT-22V412-2331.PDF" \
  -F 'configuration={"tier":"cost_effective","version":"latest"}'
curl "https://api.cloud.llamaindex.ai/api/v2/parse/$JOB_ID?expand=markdown_full" \
  -H "Authorization: Bearer $LLAMA_CLOUD_API_KEY"
```

### 5.2 Tiers and credits (Verified, docs)

| Tier (`tier` value) | Credits per page | USD per page at $1.25 per 1,000 credits |
| --- | --- | --- |
| Fast (`fast`) | 1 | $0.00125 |
| Cost-effective (`cost_effective`) | 3 | $0.00375 |
| Agentic (`agentic`) | 10 | $0.0125 |
| Agentic Plus (`agentic_plus`) | 45 | $0.05625 |

- Pin `version` (for example `"2026-01-08"`) for reproducible production runs; `"latest"` floats.
- Re-parsing the same file within 48 hours is free (cache).
- Plans: Free 10,000 credits per month, 5 concurrent parse jobs; Starter $50 per month for 40,000 credits.
- Sources: https://developers.llamaindex.ai/llamaparse/parse/guides/api-reference/, https://developers.llamaindex.ai/llamaparse/parse/guides/tiers/, https://developers.llamaindex.ai/llamaparse/general/pricing/, https://developers.llamaindex.ai/llamaparse/general/billing/

### 5.3 Python package (Verified, PyPI plus docs)

- Current: **`llama-cloud`** (2.18.0, 2026-10-09). The docs say `pip install "llama-cloud>=2.8"`.

```python
from llama_cloud import LlamaCloud
client = LlamaCloud()  # reads LLAMA_CLOUD_API_KEY
f = client.files.create(file="RCLRPT-22V412-2331.PDF", purpose="parse")
result = client.parsing.parse(file_id=f.id, tier="cost_effective", version="latest", expand=["markdown"])
print(result.markdown.pages[0].markdown)
```

`AsyncLlamaCloud` is the async variant.

PRD discrepancy (LlamaParse):
- **`llama-cloud-services` is not current.** Its PyPI page carries a deprecation notice ("maintained until May 1, 2026; migrate to `llama-cloud>=1.0`"), and its last release was 0.6.94 on 2026-02-13. `llama-parse` is in the same state.
- The v1 "modes" API still exists, but v2 uses tiers. Use v2 endpoints and tier names.

---

## 6. LLM providers

### 6.1 Anthropic (Verified, docs)

Current models (https://platform.claude.com/docs/en/about-claude/models/overview):

| Model | API id | Price, $ per million tokens (input / output) |
| --- | --- | --- |
| Claude Fable 5.1 | `claude-fable-5-1` | 10 / 50 |
| Claude Opus 5.5 | `claude-opus-5-5` | 4 / 20 |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | 2 / 10 |
| **Claude Haiku 5.5 (cheapest)** | **`claude-haiku-5-5`** | **0.10 / 0.50** for prompts up to 100,000 tokens; 0.50 / 2.50 above that |
| Claude Haiku 4.5 (legacy) | `claude-haiku-4-5-20251001` | 1 / 5 |

- All four current models have a 1M-token context window and 128K max output. Haiku 5.5 retirement is not sooner than 2027-10-07.
- Haiku 5.5 cache reads cost $0.01 per million tokens. Batch pricing for Haiku 5.5 is $0.05 / $0.25.
- Haiku 3.5 is retired (except on Google Cloud).
- Source for prices: https://platform.claude.com/docs/en/about-claude/pricing

Forcing JSON output (Verified, docs; GA, supported on `claude-haiku-5-5`):

```python
import anthropic, json
client = anthropic.Anthropic()
resp = client.messages.create(
    model="claude-haiku-5-5", max_tokens=1024,
    messages=[{"role": "user", "content": complaint_text}],
    output_config={"format": {"type": "json_schema", "schema": {
        "type": "object",
        "properties": {"component": {"type": "string"}, "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                       "symptoms": {"type": "array", "items": {"type": "string"}}},
        "required": ["component", "severity", "symptoms"], "additionalProperties": False}}},
)
data = json.loads(next(b.text for b in resp.content if b.type == "text"))
```

- With Pydantic, `client.messages.parse(..., output_format=MyModel)` returns the parsed object in `parsed_output`.
- Alternative: strict tool use, which means a tool with `input_schema`, `"strict": true` and `tool_choice: {"type": "tool", "name": "..."}`.
- Python SDK `anthropic` 1.15.0.
- Source: https://platform.claude.com/docs/en/build-with-claude/structured-outputs

Message Batches API (Verified, docs):
- `POST https://api.anthropic.com/v1/messages/batches` with `{"requests": [{"custom_id": "...", "params": {...messages params...}}]}`. `custom_id` must match `^[a-zA-Z0-9_-]{1,64}$`.
- Limits: 100,000 requests or 256 MB per batch. Most batches finish within 1 hour; they expire at 24 hours. Results are kept for 29 days. Batches cost 50% of standard pricing.
- Source: https://platform.claude.com/docs/en/build-with-claude/batch-processing

### 6.2 OpenAI (Verified, docs)

- Cheapest per token today: `gpt-5-nano` at $0.05 input / $0.40 output per million tokens. **But its only snapshot, `gpt-5-nano-2025-08-07`, shuts down on 2026-12-11**; the recommended replacement is `gpt-5.6-luna` ($0.20 / $1.20).
- The cheapest current-generation model is **`gpt-6-luna`** at $0.10 / $0.50 per million tokens (1.05M context, structured outputs supported), which OpenAI recommends for "cost-sensitive, high-volume workloads". `gpt-4.1-nano` ($0.10 / $0.40) is not on the deprecation list today but is an older generation.
- Python SDK `openai` 3.35.1.
- Sources: https://developers.openai.com/api/docs/pricing, https://developers.openai.com/api/docs/deprecations, https://developers.openai.com/api/docs/models/gpt-6-luna

Responses API structured outputs (Verified, docs):

```python
from openai import OpenAI
client = OpenAI()
resp = client.responses.create(
    model="gpt-6-luna",
    input=[{"role": "user", "content": complaint_text}],
    text={"format": {"type": "json_schema", "name": "complaint_extraction", "strict": True, "schema": {
        "type": "object",
        "properties": {"component": {"type": "string"}, "severity": {"type": "string", "enum": ["low", "medium", "high"]}},
        "required": ["component", "severity"], "additionalProperties": False}}},
)
print(resp.output_text)
# Pydantic shortcut: client.responses.parse(model=..., input=..., text_format=MyModel).output_parsed
```

For `gpt-6-luna`, Chat Completions supports function calling only with `reasoning_effort: none`; use the Responses API.

### 6.3 Ollama (Verified, docs plus library)

- Latest release v0.40.6 (2026-10-16). Python client `ollama` 0.6.3.
- Structured outputs: pass a JSON schema as `format` on `POST /api/chat` (or `/api/generate`). `"format": "json"` is the loose mode.

```bash
curl -s http://localhost:11434/api/chat -d '{
  "model": "qwen3:4b", "stream": false, "options": {"temperature": 0},
  "messages": [{"role": "user", "content": "Extract component and severity: ..."}],
  "format": {"type": "object", "properties": {"component": {"type": "string"}, "severity": {"type": "string"}},
             "required": ["component", "severity"]}}'
```

- Embeddings: `POST /api/embed` with `{"model": "nomic-embed-text", "input": ["text a", "text b"]}`, which returns `embeddings` (a list of vectors). Optional fields: `truncate` (default true), `dimensions`, `keep_alive`. `/api/embeddings` is superseded.
- Model download sizes (default Q4 tags, from https://ollama.com/library):

| Model | Download size |
| --- | --- |
| `qwen2.5:3b` | 1.9 GB |
| `llama3.2:3b` | 2.0 GB |
| `qwen3:4b` | 2.5 GB |
| `phi4-mini:3.8b` | 2.5 GB |
| `granite4:3b` (micro) | 2.1 GB |
| `gemma3:4b` | 3.4 GB |
| `qwen3.5:4b` | 3.3 GB |
| `qwen3.5:9b` | 6.6 GB |
| `qwen3:8b` | 5.2 GB |
| `nomic-embed-text` (v1.5, 137M parameters) | 274 MB, 768 dimensions |
| `embeddinggemma:300m` | 622 MB |
| `qwen3-embedding:0.6b` | 639 MB |

- Recommendation for a 16 GB M1: `qwen3:4b` or `qwen3.5:4b` as the primary JSON extractor, `llama3.2:3b` or `qwen2.5:3b` as the fast fallback, and `nomic-embed-text` for embeddings. All fit in memory alongside Docker. **Quality ranking for this task is unverified**; decide with the project's own evals.
- `nomic-embed-text` produces 768-dimension vectors, which do not match the Pinecone integrated index (1024 for `llama-text-embed-v2`). Local Ollama embeddings need their own index, or `llama-text-embed-v2` set to `dimension=768`, though vectors from different models are still not comparable.

PRD discrepancy (LLM providers):
- `gpt-5-nano` exists and is the cheapest, but it **is removed from the API on 2026-12-11**. Plan for `gpt-6-luna` (or `gpt-5.6-luna` per OpenAI's mapping).
- The current cheapest Claude is `claude-haiku-5-5` (not Haiku 4.5 or 3.5), at $0.10 / $0.50 per million tokens.
- Claude JSON output is now native (`output_config.format` with `json_schema`, GA). Forcing a tool call is no longer required.
- Newer small Ollama models (`qwen3.5:4b`, `granite4:3b`) exist beyond the PRD list.

---

## 7. MLflow (Verified, PyPI plus docs plus GHCR)

- Version 3.17.1 (2026-10-13).
- Docker image `ghcr.io/mlflow/mlflow:v3.17.1` (also `latest`, plus `-full` variants), multi-arch (`amd64`, `arm64`).
- **SQLite is now the default backend store.** Starting MLflow without a backend creates `sqlite:///mlflow.db`. The `./mlruns` file store is labeled "Legacy", still supported for backward compatibility. Some newer features (for example trace rollups) require a database backend.
- The Model Registry requires a database-backed store; SQLite qualifies.

```bash
mlflow server --backend-store-uri sqlite:////mlflow/mlflow.db \
  --artifacts-destination /mlflow/artifacts --host 0.0.0.0 --port 5000
# or reuse the stack's Postgres:
# --backend-store-uri postgresql://mlflow:pw@postgres:5432/mlflow   (image needs psycopg2; the -full variant or a pip install)
```

Client: `mlflow.set_tracking_uri("http://mlflow:5000")` or `MLFLOW_TRACKING_URI`.

Source: https://mlflow.org/docs/latest/self-hosting/architecture/backend-store/

Unverified: whether the slim (non `-full`) image includes `psycopg2`. Test it, or use SQLite.

PRD discrepancy (MLflow): a "file-based tracking URI" is the legacy option. Use `sqlite:///...` (default) or Postgres, which also enables the Model Registry.

---

## 8. Terraform on OCI

### 8.1 Always Free limits, mid to late 2026 (Verified, Oracle docs plus Oracle community post)

- **Ampere A1 (`VM.Standard.A1.Flex`): 1,500 OCPU-hours and 9,000 GB-hours per month, equivalent to 2 OCPUs and 12 GB RAM total.** Allocate as one 2-OCPU / 12 GB instance or two 1-OCPU instances. Home region only; not available in South Korea North (Chuncheon).
- The cut from 4 OCPUs / 24 GB took effect around **2026-06-15** (Oracle docs updated without announcement; Oracle Customer Connect post 2026-07-21; InfoQ and Linuxiac coverage).
- Unverified: reports that Pay-As-You-Go accounts keep 4 OCPUs / 24 GB rest on support emails, not documentation. Design for 2 OCPUs / 12 GB.
- Also Always Free: up to two `VM.Standard.E2.1.Micro` (AMD, 1/8 OCPU, 1 GB) instances; 200 GB total block storage (boot plus block) and 5 backups; 10 TB per month outbound data; one 10 Mbps flexible load balancer and one network load balancer.
- Boot volume: the docs say "minimum 47 GB" in one section and "50 GB default and minimum" in another; the Terraform docs say minimum 50 GB.
- Idle reclamation: Always Free instances may be reclaimed if, over 7 days, 95th-percentile CPU, network, and (for A1) memory utilization are all below 20%.
- "Out of host capacity" errors are common; retry or switch availability domain.
- Sources: https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm, https://community.oracle.com/customerconnect/discussion/970310/oci-always-free-updated-ampere-a1-compute-allocation, https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/

### 8.2 Provider and resources (Verified, provider docs)

- Provider `oracle/oci` v9.10.0 (2026-10-14).
- Resources: `oci_core_vcn` (use `cidr_blocks`; `cidr_block` is deprecated), `oci_core_internet_gateway`, `oci_core_route_table` (`route_rules { destination, destination_type, network_entity_id }`), `oci_core_security_list` (`ingress_security_rules` / `egress_security_rules` with `tcp_options { min, max }`), `oci_core_subnet` (`route_table_id`, `security_list_ids`, `prohibit_public_ip_on_vnic`), `oci_core_instance`, and data source `oci_core_images`.
- Ubuntu ARM images exist as `Canonical-Ubuntu-24.04-aarch64-YYYY.MM.DD-N` (latest listed 2026.09.18-0). No Ubuntu 26.04 page exists on OCI docs yet.

```hcl
terraform {
  required_providers { oci = { source = "oracle/oci", version = "~> 9.10" } }
}

data "oci_identity_availability_domains" "ads" { compartment_id = var.tenancy_ocid }

data "oci_core_images" "ubuntu_arm" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "24.04"
  shape                    = "VM.Standard.A1.Flex"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

resource "oci_core_vcn" "main" {
  compartment_id = var.compartment_ocid
  cidr_blocks    = ["10.0.0.0/16"]
  display_name   = "vsia-vcn"
  dns_label      = "vsia"
}

resource "oci_core_internet_gateway" "igw" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  enabled        = true
}

resource "oci_core_route_table" "public" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.igw.id
  }
}

resource "oci_core_security_list" "public" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.main.id
  egress_security_rules {
    destination = "0.0.0.0/0"
    protocol    = "all"
  }
  ingress_security_rules {
    protocol = "6"
    source   = var.admin_cidr
    tcp_options {
      min = 22
      max = 22
    }
  }
  ingress_security_rules {
    protocol = "6"
    source   = "0.0.0.0/0"
    tcp_options {
      min = 443
      max = 443
    }
  }
}

resource "oci_core_subnet" "public" {
  compartment_id    = var.compartment_ocid
  vcn_id            = oci_core_vcn.main.id
  cidr_block        = "10.0.1.0/24"
  route_table_id    = oci_core_route_table.public.id
  security_list_ids = [oci_core_security_list.public.id]
  dns_label         = "pub"
}

resource "oci_core_instance" "app" {
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name
  compartment_id      = var.compartment_ocid
  shape               = "VM.Standard.A1.Flex"
  shape_config {
    ocpus         = 2
    memory_in_gbs = 12
  }
  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu_arm.images[0].id
    boot_volume_size_in_gbs = 100
  }
  create_vnic_details {
    subnet_id        = oci_core_subnet.public.id
    assign_public_ip = true
  }
  metadata = {
    ssh_authorized_keys = file(var.ssh_public_key_path)
    user_data           = base64encode(file("${path.module}/cloud-init.yaml"))
  }
}
```

- `metadata.user_data` must be base64-encoded cloud-init (per the `oci_core_instance` docs). `shape_config.ocpus` and `memory_in_gbs` are updatable.
- Ubuntu images on OCI ship with restrictive iptables rules. Security list changes alone may not open 80 / 443 until the host firewall is also opened. This is common community guidance, **unverified** in Oracle docs.
- Unverified: the exact `operating_system` filter string `"Canonical Ubuntu"` (widely used; Oracle's image page lists names but not the filter value). Confirm with `oci compute image list --operating-system "Canonical Ubuntu" --shape VM.Standard.A1.Flex`.
- Sources: https://github.com/oracle/terraform-provider-oci/tree/master/website/docs (`r/core_instance`, `d/core_images`, `r/core_vcn`, `r/core_subnet`, `r/core_internet_gateway`, `r/core_route_table`, `r/core_security_list`), https://docs.oracle.com/en-us/iaas/images/ubuntu-2404/index.htm

Capacity note: 12 GB must host Postgres, n8n, Open WebUI, MLflow, and the agent API. **Do not plan to run Ollama models on the OCI VM** beyond a 1 to 3B model. Keep Ollama on the 16 GB M1 for development and use the hosted APIs in the cloud.

PRD discrepancy (OCI): the PRD claim is **correct**. The Always Free A1 allowance is now 2 OCPUs / 12 GB (effective about 2026-06-15). Any older plan that sized for 4 OCPUs / 24 GB must be resized.

---

## 9. Streamlit Community Cloud (Verified, docs)

- Dependency file location: the repository root or the same directory as the entrypoint file. Precedence: `uv.lock`, then `Pipfile`, then `environment.yml`, then `requirements.txt`, then `pyproject.toml` (Poetry). `requirements.txt` is installed with uv, falling back to pip. System packages go in `packages.txt`.
- Pin `streamlit` (current 1.66.0) to avoid surprise upgrades.
- Only one `.streamlit/config.toml` is recognized, at the repository root; apps always initialize from the repository root even if the entrypoint is in a subdirectory.
- Secrets: never commit `.streamlit/secrets.toml`. Paste its contents into the app's "Advanced settings" when deploying (editable later in app settings). Read with `st.secrets["KEY"]`. Python version is selected in the same dialog; only supported, non-end-of-life versions are allowed.
- Sleep: apps with **no traffic for 12 hours go to sleep**. Any viewer can wake one with "Yes, get this app back up!"
- Resource limits (as of Feb 2024, "may change"): up to 2 CPU cores, 2.7 GB memory, 50 GB storage. Apps are hosted in the US. GitHub-triggered updates are limited to 5 per minute.
- Sources: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies, https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management, https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization, https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app, https://docs.streamlit.io/deploy/streamlit-community-cloud/status

Design implication: a sleeping Streamlit app adds wake-up latency to the first demo visit, and a Streamlit app calling the OCI backend needs that backend reachable over HTTPS. Unverified: the default Python version Community Cloud selects today.

---

## 10. Summary of PRD discrepancies

1. NHTSA complaint model strings are year-specific (Mach-E 2023+ is `MUSTANG MACH-E BEV`; Tesla Model Y 2022 is `MODEL Y  5-SEAT` / `MODEL Y 7-SEAT`, 2023 to 2024 `MODEL Y (All Variants)`, 2025 `MODEL Y`).
2. NHTSA recall strings differ from complaint strings (`MUSTANG MACH E`, `F-150 LIGHTNING BEV`, `RAV4 PLUG-IN HYBRID`); a wrong string returns HTTP 400 with `Count: 0`.
3. NHTSA official recall endpoints return no document links; `safetyIssues/byNhtsaId` (unofficial) does, and PDF filenames carry an unpredictable 4-digit id.
4. `FLAT_RCL.zip` and `FLAT_TSBS.zip` do not exist; use `FLAT_RCL_POST_2010.zip` and `TSBS_RECEIVED_<range>.zip` / `MFR_COMMS_RECEIVED_<range>.zip`.
5. n8n: `WEBHOOK_URL` is deprecated (use `N8N_WEBHOOK_URL`); `toolHttpRequest` is hidden/legacy (use `n8n-nodes-base.httpRequestTool` or `toolWorkflow`).
6. Pinecone SDK 10.0.0 methods are keyword-only; the positional examples in the docs fail. Starter plan is `us-east-1` only.
7. LlamaParse: `llama-cloud-services` is deprecated; use `llama-cloud` (>=2.8) and the v2 `/api/v2/parse/*` endpoints with tiers.
8. OpenAI `gpt-5-nano` shuts down on 2026-12-11; use `gpt-6-luna` (or `gpt-5.6-luna`).
9. Cheapest Claude is `claude-haiku-5-5` ($0.10 / $0.50 per million tokens); native JSON via `output_config.format`.
10. MLflow file store is legacy; SQLite is the default and supports the Model Registry.
11. OCI Always Free A1 cut to 2 OCPUs / 12 GB is confirmed (the PRD is right).
