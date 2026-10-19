# AGENTS.md: how to work in this repo

Read this before changing anything. It applies to people and coding agents alike.

## What this project is

Vehicle Service Intelligence Agent (VSIA): an AI workflow system on public NHTSA data. It ingests owner
defect complaints and recall documents, triages each complaint with an LLM (extract fields, classify
component and severity, link known recalls through retrieval, score confidence), routes uncertain cases
to human review, answers questions with cited sources (RAG), and forecasts weekly complaint volume per
component with spike alerts. The pattern (ingest, extract, retrieve, agent triage with human review,
forecast, dashboard) is domain-agnostic: it applies equally to insurance claims, support tickets or
healthcare referrals. Keep domain specifics in `config/settings.yaml`, loaders and prompts.

## Hard rules

1. **Never name any prospective employer** in code, docs, commits or demo text. Frame the problem as
   "defect intelligence for vehicle quality and service teams".
2. **Never invent results.** Every number in docs comes from a script that produced it; cite the script
   and the run (MLflow run id or the report file). Unmeasured cells say "not yet measured".
3. **Label leakage:** `complaints.components_raw` and `component_primary` are NHTSA's coded labels. They
   must never be shown to an LLM or used as model input at triage time. They are ground truth for eval.
4. **PII:** call `vsia.guardrails.redact()` on complaint text before it reaches an LLM, an embedding model
   or a log line. Never log prompt text; log only metadata (see `vsia.llm`).
5. **Secrets** live in `.env` (gitignored). Code must run with zero keys: Ollama + local vector store.
6. **No emojis**, plain English, complete sentences in docs.
7. Disk on the dev laptop is tight (about 7 GB free). Do not download multi-GB artifacts or Docker images.
   Ask before adding a dependency larger than about 100 MB.

## Layout and ownership

| Path | Owner workstream | Notes |
|---|---|---|
| `config/settings.yaml` | cross-cutting | Domain config: segment, taxonomy, severity rubric, thresholds, model ids, prices |
| `src/vsia/config.py`, `schemas.py`, `db.py`, `taxonomy.py` | core (contracts) | Change only with a decision record; schemas are contracts |
| `src/vsia/nhtsa.py`, `ingest.py` | ingestion | NHTSA client; also the agent's recall-lookup tool |
| `src/vsia/llm.py` | LLM gateway | `complete_json()` for all LLM calls; `embed_ollama()` |
| `src/vsia/guardrails.py` | guardrails | `redact()`, injection handling |
| `src/vsia/documents.py`, `retrieval.py` | parsing and retrieval | LlamaParse or local parser; vector stores (local, Pinecone); hybrid search |
| `src/vsia/classifier.py` | evaluation and baselines | TF-IDF baseline classifier (also a confidence signal) |
| `src/vsia/agent.py`, `review.py`, `api.py`, `cli.py` | triage agent and HITL | Triage workflow, review queue, FastAPI service, CLI |
| `pipelines/` | forecasting | Forecast pipeline, MLflow |
| `eval/` | evaluation | Gold set builder, eval runner |
| `app/` | dashboard | Streamlit |
| `workflows/n8n/` | orchestration | Exported n8n workflow JSON |
| `openwebui/` | chat | Open WebUI Pipe function |
| `infra/` | infrastructure | Terraform (OCI + Pinecone), Docker Compose |
| `docs/` | everyone | See docs map in `docs/README.md` |

## Contracts you can rely on

- Database: `vsia.db.engine()` returns a SQLAlchemy engine (SQLite locally at `data/vsia.db`, Postgres via
  `DATABASE_URL`). Tables are defined in `vsia/db.py`; use SQLAlchemy Core, keep SQL portable.
- Data loaded today: about 10,300 complaints (8 makes, filed 2022-01-02 to 2026-10-15) and 200 recall
  campaigns (407 vehicle rows).
- LLM: `vsia.llm.complete_json(system, user, PydanticModel, purpose=..., prompt_version=..., ref_id=...)`
  returns `LLMResult(data, call, raw_text)` and logs to `llm_calls`. Providers: `ollama` (default,
  `qwen2.5:3b`), `anthropic` (`claude-haiku-5-5`), `openai` (`gpt-6-luna`), `gemini`
  (`gemini-2.5-flash-lite`, free tier) and `groq` (`openai/gpt-oss-20b`, free tier); Gemini and Groq use
  their OpenAI-compatible Chat Completions endpoints (ADR-0088).
- Embeddings: `vsia.llm.embed_ollama(texts)` returns 768-dimension vectors (`nomic-embed-text`).
- Python: `.venv` (Python 3.11). Run `source .venv/bin/activate`. Install with `uv pip install ...`.
- Network calls need the shell to run outside the sandbox.

## Decision records

Every non-obvious choice gets a MADR-style record in `docs/decisions/NNNN-title.md` using
`docs/decisions/0000-template.md`. Always include options considered, trade-offs accepted and a
"revisit when" trigger. Number ranges by workstream (to avoid collisions when working in parallel):

| Range | Workstream |
|---|---|
| 0001-0019 | cross-cutting and core |
| 0020-0029 | guardrails and LLM gateway |
| 0030-0039 | document parsing and retrieval |
| 0040-0049 | gold set, baselines and evaluation |
| 0050-0059 | forecasting and MLflow |
| 0060-0069 | triage agent and human review |
| 0070-0079 | dashboard, chat and n8n orchestration |
| 0080-0089 | infrastructure and deployment |

## Testing

`pytest` from the repo root. Tests must not need network or API keys (mock HTTP; skip Ollama tests when the
server is not reachable).
