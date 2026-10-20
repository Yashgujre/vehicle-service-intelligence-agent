# Documentation map

Where to find each document, grouped by the question it answers. Start with the design doc, then follow
the links for the part you care about.

## Start here

| Document | Answers |
|---|---|
| [Design doc](design/design-doc.md) | What the system does, why it is built this way, open questions and rollout |
| [System card](models/system-card.md) | The deployed AI system as assembled: models, safeguards, measured results, limits |
| [Decision log](decisions/README.md) | Every architecture decision (ADR-0001 onward) with options and trade-offs |
| [Hosted demo runbook](operations/runbooks/hosted-demo.md) | How the free public demo is deployed, refreshed and kept within quota |

## Architecture

| Document | Answers |
|---|---|
| [C4 context](architecture/c4-context.md), [container](architecture/c4-container.md), [triage component](architecture/c4-component-triage.md) | The system at three zoom levels |
| [Sequences](architecture/sequences.md) | Step-by-step flows for ingestion, triage, review, chat, forecasting and document parsing |
| [Data flow](architecture/data-flow.md) | Which component reads and writes which table |
| [Deployment](architecture/deployment.md) | The VM design and the hosted demo |
| [Dashboard](architecture/dashboard.md) | Each page, what it shows and where its data comes from |

## Data

| Document | Answers |
|---|---|
| [Corpus datasheet](data/datasheet-nhtsa-corpus.md) | What the NHTSA complaints and recalls are, and their limits |
| [Gold-set datasheet](data/datasheet-gold-set.md) | How the evaluation labels were built (silver labels) and what they can claim |
| [Data dictionary](data/data-dictionary.md) | Every table and column |
| [Lineage](data/lineage.md) | Where each derived dataset comes from |

## AI: prompts, tools, models and evaluation

| Document | Answers |
|---|---|
| [Triage prompt](llm/prompts/triage.md), [RAG prompt](llm/prompts/rag.md), [recall extraction prompt](llm/prompts/recall-extraction.md) | Each prompt, its inputs, output schema and version history |
| [Agent tools](llm/tools.md) | The tools the triage agent calls and their contracts |
| [Evaluation plan](evaluation/eval-plan.md), [metrics](evaluation/metrics.md) | What is measured and how each metric is defined |
| [Model comparison](evaluation/model-comparison.md), [reports](evaluation/reports/) | Measured results per model on the gold split (generated) |
| [Baseline classifier](evaluation/baseline-classifier.md) | The offline TF-IDF classifier and its results (generated) |
| [Labeling guide](evaluation/labeling-guide.md) | How a person hand-verifies gold labels |
| [Forecaster model card](models/model-card-forecaster.md), [backtest](models/backtest-report.md) | The weekly volume forecast and spike alerts |
| [Human review workflow](hitl/review-workflow.md) | Confidence, routing reasons, the review queue and how decisions become labels |

## Security and responsible AI

| Document | Answers |
|---|---|
| [Threat model](security/threat-model.md), [data-flow diagram](security/data-flow-diagram.md) | Trust boundaries and threats, including the public demo |
| [Guardrails](security/guardrails.md) | Prompt-injection checks, citation grounding, output validation |
| [PII handling](security/pii-handling.md) | What is redacted, where, and the measured residual |
| [AI risk register](security/ai-risk-register.md) | Open and closed AI risks with owners and mitigations |

## Operations

| Document | Answers |
|---|---|
| [SLOs](operations/slos.md), [observability](operations/observability.md) | Targets and how they are measured |
| [Cost model](operations/cost-model.md) | Cost per 1,000 triages per model and the free-tier limits |
| [Incident playbook](operations/incident-playbook.md), [runbooks](operations/runbooks/) | What to do when ingestion, a provider, cost or the review backlog goes wrong |

## Research

| Document | Answers |
|---|---|
| [Documentation process research](research/01_documentation_process_research.md) | Which documents a production AI system needs, with sources |
| [Technical verification](research/02_technical_verification.md) | Checks of tool and API facts the design relies on |
