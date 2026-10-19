# How Professional AI / LLM Workflow Engineers Document a System End to End

Research note for the Vehicle Service Intelligence Agent project.
Researched: 2026-10-18. All sources were fetched on that date; each claim below is tied to a source in the Sources list. Where something could not be verified from a primary source, the text says so.

---

## (a) The professional process in six phases

Professional teams do not write one large specification. They write a set of small, linked documents, each produced at the phase where the information first exists, and each kept up to date as the system changes. Michael Nygard's original argument for decision records makes the point directly: large documents are never kept up to date and nobody reads them, while small, modular documents have a chance of staying current [S3].

| Phase | Question the phase answers | Documents produced |
| --- | --- | --- |
| 1. Discover | What problem are we solving, for whom, with what data? | Problem statement and goals/non-goals (first part of the design doc), dataset datasheets for the source data, initial risk register |
| 2. Design | How will the system work? | Technical design document (RFC), C4 context and container diagrams, data flow diagram with trust boundaries, sequence diagrams for agent and tool calls, data contracts, prompt and tool specifications |
| 3. Decide | Which option did we choose and why? | Architecture Decision Records (ADRs) and a decision log index |
| 4. Build | How is it built and run locally? | README, infrastructure docs (Terraform, Docker Compose), data dictionary generated from contracts, prompt registry entries, model and experiment tracking setup |
| 5. Evaluate | Does it work well enough to ship, and did a change make it worse? | Evaluation plan, gold-set datasheet, metric definitions, eval reports per release, forecasting backtest report, model card, system card |
| 6. Operate | How do we keep it healthy, safe, and affordable? | SLOs, runbooks, incident playbook, cost model, observability spec, threat model updates, human-review operations guide |

Threat modeling and evaluation are not one-time steps. The OWASP Threat Modeling Cheat Sheet says a threat model should be maintained alongside the system and started in design [S20]; OpenAI's evaluation guidance recommends continuous evaluation on every change and growing the eval set over time [S17]; the NIST AI RMF treats Govern as a cross-cutting function infused through Map, Measure, and Manage [S22].

---

## (b) Recommended documentation set for this project

All paths are relative to the repository root. Templates and standards are cited in section (c).

| Doc name | File path | Purpose | Key sections | Source or standard it follows |
| --- | --- | --- | --- | --- |
| README | `README.md` | First stop for any reader: what it does, how to run it, where docs live | What it does; why it is useful; quickstart (Docker Compose); architecture diagram link; docs map; maintainers | GitHub README guidance [S31] |
| Technical design document | `docs/design/design-doc.md` | The single narrative of the whole system and its trade-offs | Context and scope; goals and non-goals; design (system-context diagram, APIs, data storage); alternatives considered; cross-cutting concerns (security, privacy, observability, cost); SLAs/dependencies; testing and rollout | Google design doc anatomy [S1]; Uber RFC sections as reported in [S2] |
| Architecture views | `docs/architecture/c4-context.md`, `c4-container.md`, `c4-component-triage-agent.md`, `deployment.md` | Diagrams at the right zoom level for each audience | System context; containers (n8n, triage agent service, vector store, Postgres, MLflow, Streamlit); component view of the triage agent only; deployment view (Terraform + Compose) | C4 model [S6, S7] |
| arc42 overview (optional) | `docs/architecture/arc42.md` | A checklist-shaped index if a reviewer expects a full architecture document | Sections 1 to 12, with sections 5, 6, 7 linking to the C4 files and section 9 linking to the ADR log | arc42 [S8] |
| Decision log and ADRs | `docs/decisions/README.md` (index) and `docs/decisions/NNNN-title.md` | Record each significant decision with alternatives and consequences | Status; context and problem; decision drivers; considered options; decision outcome; consequences (good and bad); confirmation; pros and cons per option | MADR 4.0 [S5]; Nygard format [S3]; Azure Well-Architected ADR guidance [S4] |
| Data flow diagram and trust boundaries | `docs/security/data-flow-diagram.md` | Show every data store, process, external entity, and where untrusted data crosses into trusted zones | External entities (NHTSA API, users, LLM provider); processes; stores; trust boundaries; PII path | OWASP Threat Modeling Cheat Sheet [S20] |
| Sequence diagrams | `docs/architecture/sequences.md` | Show the runtime order of agent, tool, retrieval, and review calls | Complaint triage; low-confidence routing to review; RAG chat with citations; weekly forecast and alert | C4 dynamic diagram [S7]; MCP tool message flow example [S13] |
| Data lineage | `docs/data/lineage.md` | Trace each output (triage record, forecast, chat answer) back to source files and job runs | Datasets, jobs, runs; source-to-table mapping; lineage events | OpenLineage core model [S11] |
| Data contracts and data dictionary | `docs/data/contracts/*.yaml`, `docs/data/data-dictionary.md` | Fix the schema, quality rules, and owners for every pipeline table | Fundamentals; schema (field, type, description, PII flag); data quality rules; SLA (freshness); team and roles | Open Data Contract Standard (ODCS) [S10] |
| Datasheets for datasets | `docs/data/datasheet-nhtsa-corpus.md`, `docs/data/datasheet-gold-set.md` | Describe where the complaint/recall corpus and the gold set came from and how they may be used | Motivation; composition; collection process; preprocessing/cleaning/labeling; uses; distribution; maintenance | Gebru et al., Datasheets for Datasets [S9]; NHTSA dataset page [S33] |
| Prompt specifications | `docs/llm/prompts/<prompt-name>.md` | One spec per prompt: role, inputs, output schema, version history, eval link | Name and version; purpose; variables; output format; model config; change log with eval results; registry URI | MLflow Prompt Registry [S14]; OTel `gen_ai.prompt.name` and `gen_ai.prompt.version` [S24] |
| Tool specifications | `docs/llm/tools.md` | Describe each agent tool as a contract | Name; description; input schema; output schema; errors; side effects; who can approve; rate limits | MCP tool definition [S13]; Anthropic tool design guidance [S12] |
| Model card (forecaster) | `docs/models/model-card-forecaster.md` | Describe the complaint-volume forecasting model | Model details; intended use; factors; metrics; evaluation data; training data; quantitative analyses; ethical considerations; caveats | Mitchell et al., Model Cards [S15] |
| System card | `docs/models/system-card.md` | Describe the deployed LLM system as assembled: models, prompts, retrieval, guardrails, human review | Models used and routing; data sources; safeguards; evaluation results of the assembled system; known limitations; deployment context | NTIA AI system disclosures [S16]; UK MOD system card guidance [S35] |
| Evaluation plan and metric definitions | `docs/evaluation/eval-plan.md`, `docs/evaluation/metrics.md` | Define what "good" means before measuring | Objectives; datasets (gold set); evaluator types (metric, human, LLM-as-judge); metric formulas; pass thresholds; regression policy | OpenAI evaluation best practices [S17]; Zheng et al. on LLM-as-judge [S18] |
| Eval reports | `docs/evaluation/reports/YYYY-MM-DD-<version>.md` | Record each run against the gold set | Versions under test (prompt, model, retriever); scores per metric and per slice; diff versus last baseline; failures reviewed; decision | Same as above |
| Human-in-the-loop design | `docs/hitl/review-workflow.md` | Define confidence thresholds, the review queue, and how corrections become labels | Confidence score definition; threshold and rationale; random audit sampling; reviewer UI; label schema; feedback loop into gold set | AWS Augmented AI pattern [S19]; Microsoft HAX guidelines [S34]; OWASP LLM01 mitigation 5 [S27] |
| Observability spec | `docs/operations/observability.md` | Define spans, attributes, and dashboards for tracing, cost, and latency | Span types (chat, embeddings, retrieval, tool); attributes; token and cost fields; latency percentiles; model routing fields | OpenTelemetry GenAI semantic conventions [S23, S24] |
| Threat model | `docs/security/threat-model.md` | STRIDE pass over the DFD plus OWASP LLM Top 10 mapping | Assets; DFD reference; STRIDE table per trust boundary; OWASP LLM01 to LLM10 mapping; response (mitigate, eliminate, transfer, accept) | Microsoft STRIDE [S21]; OWASP cheat sheet [S20]; OWASP LLM Top 10 2025 [S26]; Microsoft AI/ML threat modeling [S28] |
| AI risk register | `docs/security/ai-risk-register.md` | Track AI-specific risks against NIST functions | Risk; NIST function (Govern, Map, Measure, Manage); owner; control; status | NIST AI RMF 1.0 and AI 600-1 [S22, S25] |
| PII handling | `docs/security/pii-handling.md` | Define what counts as PII in complaint text and how it is redacted before storage, embedding, and prompting | PII categories; detection method; redaction point in the pipeline; logging rules | Microsoft Presidio [S29]; OWASP LLM02 [S26] |
| SLOs | `docs/operations/slos.md` | Targets for availability, triage latency, freshness, and review backlog | SLI definitions; SLO targets; error budget; measurement window | Google SRE book [S30] |
| Runbooks and incident playbook | `docs/operations/runbooks/*.md`, `docs/operations/incident-playbook.md` | Step-by-step response for known failures | Symptom; diagnosis; mitigation; rollback (prompt alias, model alias); escalation; incident roles | Google SRE book and workbook [S32, S36] |
| Cost model | `docs/operations/cost-model.md` | Expected and observed cost per complaint, per chat, per week | Token assumptions; price table with date; volume scenarios; budget alarms | Derived from token attributes in [S24]; no single standard found (see topic 11) |
| Forecasting backtest report | `docs/models/backtest-report.md` | Show the forecaster beats simple baselines on rolling-origin evaluation | Baselines (naive, seasonal naive, mean, drift); rolling-origin setup; horizon; metrics (MAE, MASE); spike-alert precision | Hyndman and Athanasopoulos, FPP3 [S37]; MLflow tracking and registry [S38, S39] |

---

## (c) Findings by topic

### 1. Design docs and RFCs

- Google's design docs follow a loose structure: context and scope; goals and non-goals; the actual design (system-context diagram, APIs, data storage, code and pseudo-code, degree of constraint); alternatives considered; and cross-cutting concerns such as security, privacy, and observability [S1].
- The same source says the design doc is "the place to write down the trade-offs you made," and that the main value of review is catching issues early, when changes are still cheap [S1].
- The design doc lifecycle is creation and rapid iteration, review, implementation and iteration, then maintenance and learning [S1].
- A compilation of public RFC templates reports Uber's RFC structure for services (used up to around 2019) as: approvers, abstract, architecture changes, service SLAs, service dependencies, load and performance testing, multi data-center concerns, security considerations, testing and rollout, metrics and monitoring, and customer support considerations [S2]. This is a secondary source; I could not find Uber's own template publicly.
- The same compilation notes that product requirement documents commonly run alongside engineering design docs, and that some companies (for example Peloton, as quoted) use ADRs for decisions and longer design docs to supplement them [S2].

Implication for this project: one design doc carries the narrative; ADRs carry the individual decisions; cross-cutting concerns should explicitly include LLM cost, guardrails, and human review.

### 2. Architecture Decision Records and decision logs

- Nygard's format (2011) has five parts: Title, Context, Decision, Status, Consequences. Context is value-neutral facts and forces in tension; Decision is stated in active voice ("We will..."); Status is proposed, accepted, deprecated, or superseded; Consequences lists positive, negative, and neutral effects. Records are numbered sequentially, never reused, and a reversed decision is kept and marked superseded. Each ADR should be one or two pages, written in full sentences [S3].
- MADR 4.0.0 (released 2024-09-17) adds structure for trade-offs: Context and Problem Statement, Decision Drivers, Considered Options, Decision Outcome ("Chosen option: X, because..."), Consequences (Good, because / Bad, because), Confirmation (how compliance will be checked), Pros and Cons of the Options, and More Information. Optional front matter records status, date, decision-makers, consulted, and informed. MADR recommends files in `docs/decisions/NNNN-title-with-dashes.md` [S5].
- Microsoft's Well-Architected guidance treats the ADR set as an append-only log: do not edit accepted records; write a superseding record and link both. It recommends recording options considered, trade-offs, a confidence level for the decision, and status, and keeping the log with the workload's documentation as a single source of truth [S4].

Implication: use MADR for every ADR so that alternatives and trade-offs are mandatory fields; keep a `docs/decisions/README.md` index as the decision log. Candidate ADRs for this project include: n8n versus code-only orchestration; choice of vector store; confidence threshold for human review; LLM provider and routing policy; forecasting model family; Streamlit versus a web framework.

### 3. C4 model and arc42

- C4 defines four hierarchical abstractions (software systems, containers, components, code) and matching diagrams (system context, container, component, code), plus three supporting diagrams: system landscape, dynamic, and deployment. It is notation and tooling independent [S6].
- C4's own guidance: "you don't need to use all 4 levels of diagram; only those that add value - the system context and container diagrams are sufficient for most software development teams" [S7].
- arc42 is a 12-section template: 1 Introduction and Goals, 2 Constraints, 3 Context and Scope, 4 Solution Strategy, 5 Building Block View, 6 Runtime View, 7 Deployment View, 8 Crosscutting Concepts, 9 Architecture Decisions, 10 Quality Requirements, 11 Risks and Technical Debt, 12 Glossary. Its documentation tags "thorough" for formal or audited environments and "essential" for items always worth documenting, such as quality goals [S8].

When to use each: C4 is a diagramming approach; arc42 is a document outline. For a portfolio-scale project, C4 context plus container diagrams, a component diagram only for the triage agent, a dynamic (sequence) diagram set, and a deployment diagram are enough. arc42 is useful as a completeness checklist; its sections 3, 5, 6, and 7 line up naturally with C4 context, container/component, dynamic, and deployment views. That mapping is my own inference, not a statement found on either official site.

### 4. Data flow diagrams, trust boundaries, sequence diagrams, lineage

- The OWASP Threat Modeling Cheat Sheet calls data flow diagrams "arguably the most common approach" for the system-modeling step, and says the model must give a clear view of trust boundaries, data flows, data stores, processes, and external entities, since these are likely attack points [S20].
- Microsoft's AI/ML threat modeling guidance says to change how trust boundaries are viewed: assume compromise or poisoning of training data and the data provider, treat training data stores as in scope, and track provenance and lineage of data [S28]. For this project, public NHTSA complaint text is untrusted input that crosses into the LLM prompt and the vector store.
- C4 includes a "dynamic" supporting diagram for runtime interactions [S7]. The MCP specification itself documents tool discovery and invocation with a sequence diagram (LLM, client, server: `tools/list`, `tools/call`, result) [S13], which is a good model for documenting agent-tool calls.
- OpenLineage is an open standard for lineage metadata built on dataset, job, and run entities, extended with "facets." It is an LF AI and Data Foundation graduate project [S11].

### 5. Data contracts, data dictionary, schema docs

- The Open Data Contract Standard (ODCS, maintained by the Bitol project) defines a YAML data contract with sections including Fundamentals, Schema, Data Quality, Support and Communication Channels, Team, Roles, Service-Level Agreement, Infrastructures and Servers, Authoritative Definitions, and Tags. It is intended to be platform agnostic [S10].
- NHTSA publishes complaints and recalls as downloadable flat files with import instructions, and provides an API, for example `api.nhtsa.gov/recalls/recallsByVehicle?make=...&model=...&modelYear=...`. NHTSA states complaint data is used to identify safety issues and to monitor recalls for proper scope [S33]. The source file layouts belong in the data dictionary.

Implication: write one ODCS contract per table (raw complaints, raw recalls, triage results, review labels, weekly volumes, forecasts) and generate the human-readable data dictionary from them so they cannot drift.

### 6. LLM-specific artifacts

Prompt specifications and versioning
- MLflow Prompt Registry treats prompts like code: each version is immutable, carries a commit message, and can be diffed side by side; mutable aliases such as `production` or `staging` point to versions so the application loads `prompts:/name@production` and rollback is an alias change. A prompt object can carry a `response_format` and a `model_config` [S14].
- OpenTelemetry's GenAI conventions include `gen_ai.prompt.name` and `gen_ai.prompt.version` attributes, so each trace can record which prompt version produced it [S24].

Tool specifications
- The MCP specification defines a tool as `name`, optional `title`, `description`, `inputSchema` (JSON Schema), optional `outputSchema`, and optional `annotations`. It distinguishes protocol errors from tool execution errors (`isError: true`). Servers must validate inputs, enforce access control, rate limit, and sanitize outputs; clients should confirm sensitive operations, validate results before passing them to the LLM, apply timeouts, and log tool usage for audit. It also says there should always be a human able to deny tool invocations [S13].
- Anthropic's guidance says tool definitions deserve as much prompt engineering as the main prompt, and a good tool definition includes example usage, edge cases, input format requirements, and clear boundaries from other tools. It distinguishes workflows (predefined code paths) from agents (LLM-directed) and recommends the simplest option that works [S12]. The page carries a note that its tooling landscape has changed since December 2024; the design principles still apply.

Model cards
- Mitchell et al. propose short (one to two page) model cards with sections: Model Details, Intended Use, Factors, Metrics, Evaluation Data, Training Data, Quantitative Analyses, Ethical Considerations, Caveats and Recommendations, with results broken down by relevant groups and conditions [S15].

System cards
- NTIA describes system cards as disclosures about how entire AI systems, often several models working together, perform a task, including deployment context and real-world interactions [S16]. UK Ministry of Defence guidance describes them as a single source of truth for a deployed AI system and its environment [S35]. I did not find a single formal academic template equivalent to the model card paper; treat the system card structure as convention.

Datasheets for datasets
- Gebru et al. organize datasheet questions by dataset lifecycle stage: Motivation, Composition, Collection Process, Preprocessing/Cleaning/Labeling, Uses, Distribution, Maintenance [S9]. This applies to both the NHTSA corpus and the gold set (whose labels come from human review).

### 7. Evaluation documentation

- OpenAI's evaluation guidance recommends eval-driven development, logging everything so logs can be mined for eval cases, automating scoring, and calibrating automated scorers against human judgment. Its process is: define the objective, collect a dataset, define metrics, run and compare, then continuously evaluate on every change and grow the eval set [S17].
- The same guide lists three evaluator types: metric-based (exact match, function-call accuracy and similar, useful for automated regression testing), human (highest quality, slow and expensive; use scored examples and pass/fail thresholds), and LLM-as-judge (pairwise, single-answer, or reference-guided grading) [S17].
- LLM-as-judge caveats, from Zheng et al. (MT-Bench and Chatbot Arena): judges show position bias, verbosity bias, self-enhancement bias, and limited reasoning ability. In their position test, only the strongest judge gave consistent results in more than 60 percent of swapped-order cases. After mitigation, a strong judge reached over 80 percent agreement with human preferences, about the same as human-human agreement [S18]. OpenAI's guide adds: control for response length, prefer pairwise or pass/fail, and only scale the judge once it consistently agrees with human labels [S17].

Implication: the eval plan should define each metric with a formula (for example field-extraction exact match, component-classification macro-F1, severity accuracy, recall-link precision and recall at k, citation faithfulness for RAG chat, review-routing rate), name the gold-set version, and set a regression rule (for example, block a prompt alias change if any metric drops by more than an agreed margin). The thresholds themselves are project decisions and should be recorded as ADRs.

### 8. Human-in-the-loop design

- AWS's Augmented AI documentation describes the standard pattern: route low-confidence predictions, or a random sample of predictions, to human reviewers, and use reviewer output to incrementally retrain the model [S19]. Note: the same page says Amazon A2I is no longer open to new customers; the pattern is still the reference, but the service is not a forward-looking choice.
- Microsoft's HAX Toolkit offers 18 evidence-based guidelines for human-AI interaction, organized by when they apply: initially, during interaction, when the AI is wrong, and over time [S34].
- OWASP LLM01 lists "require human approval for high-risk actions" as a prompt-injection mitigation [S27], and MCP says a human should be able to deny tool invocations [S13].

Implication: document the confidence score's definition (how it is computed and calibrated), the threshold and its ADR, a random audit sample of high-confidence cases (so the threshold itself is checked), the review queue's service level, the label schema, and how accepted corrections enter the gold set with a datasheet update.

### 9. LLMOps and observability

- Significant 2026 change: OpenTelemetry semantic conventions v1.42.0 (published 2026-06-12) deprecated all `gen_ai.*` attributes, metrics, events, and spans in the main repository and moved them to a dedicated repository, `open-telemetry/semantic-conventions-genai`, which also covers MCP and provider-specific conventions [S23, S24].
- Attributes relevant to this project (all marked "Development" stability, so they may still change): `gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.input_tokens` (should include cached tokens), `gen_ai.usage.output_tokens`, `gen_ai.agent.name`, `gen_ai.tool.name`, `gen_ai.data_source.id` (for RAG stores), `gen_ai.retrieval.query.text`, `gen_ai.retrieval.top_k`, `gen_ai.retrieval.documents`, and `gen_ai.prompt.name` / `gen_ai.prompt.version` [S24].
- Model switching and routing: Anthropic describes routing as classifying an input and sending it to a specialized path, including sending easy questions to smaller, cheaper models and hard ones to more capable models [S12]. Recording both `gen_ai.request.model` and `gen_ai.response.model` on every span makes routing decisions auditable [S24].
- MLflow's Prompt Registry integrates with MLflow tracing and evaluation for lineage [S14].

Implication: the observability spec should list span types, required attributes, how cost is computed from token counts and a dated price table, and latency percentiles per operation. Because the conventions are still in development, pin the convention version in the doc.

### 10. Security and risk

OWASP Top 10 for LLM Applications, 2025 version [S26]:

1. LLM01:2025 Prompt Injection
2. LLM02:2025 Sensitive Information Disclosure
3. LLM03:2025 Supply Chain
4. LLM04:2025 Data and Model Poisoning
5. LLM05:2025 Improper Output Handling
6. LLM06:2025 Excessive Agency
7. LLM07:2025 System Prompt Leakage
8. LLM08:2025 Vector and Embedding Weaknesses
9. LLM09:2025 Misinformation
10. LLM10:2025 Unbounded Consumption

- LLM01 explicitly covers indirect prompt injection from external content such as files and websites, and a RAG scenario where a modified document alters outputs. Mitigations include constraining model behavior, validating output formats with deterministic code, input and output filtering, least privilege, human approval for high-risk actions, segregating and labeling untrusted external content, and adversarial testing. OWASP states it is unclear whether fool-proof prevention exists [S27]. This directly supports the project's "prompt-injection-as-data" design: complaint text is wrapped and labeled as data, never as instructions.
- NIST AI RMF 1.0 (January 2023) has four functions: Govern (cross-cutting), Map, Measure, Manage [S22]. NIST AI 600-1 (July 2024) is the Generative AI Profile, with suggested actions tagged by function [S25]. NIST's page states AI RMF 1.0 is being revised as part of the White House AI Action Plan [S22], so cite version numbers.
- STRIDE categories: Spoofing (violates authentication), Tampering (integrity), Repudiation (accounting/non-repudiation), Information Disclosure (confidentiality), Denial of Service (availability), Elevation of Privilege (authorization) [S20, S21]. OWASP recommends applying STRIDE per component, data flow, and trust boundary, then choosing a response for each threat: mitigate, eliminate, transfer, or accept, and turning mitigations into testable requirements [S20].
- Microsoft's AI/ML threat modeling guidance identifies data poisoning as a leading ML threat and asks teams to identify actions a model could take that cause harm and to inventory all AI/ML dependencies in the supply chain [S28].
- PII: Microsoft Presidio is an open-source framework for detecting, redacting, masking, and anonymizing PII in text, images, and structured data [S29]. Document where redaction happens (before storage, before embedding, before prompting, before logging), because traces that record prompt text can otherwise leak PII (OWASP LLM02 [S26]).

Mapping LLM-specific threats onto STRIDE (for example, prompt injection as Tampering or Elevation of Privilege) is common practice, but I did not find an official OWASP or Microsoft table that defines this mapping; the threat model should state its own mapping.

### 11. Operational documents

- SLI, SLO, error budget: an SLI is a carefully defined quantitative measure of service level; an SLO is a target value or range for an SLI; an error budget is the allowed rate of missing SLOs, tracked daily or weekly [S30].
- Runbooks/playbooks: Google SRE reports that recording best practices ahead of time in a playbook produced "roughly a 3x improvement in MTTR" compared with "winging it" [S36].
- Incident response: the SRE workbook describes the "three Cs" (coordinate, communicate, control) and three roles: Incident Commander, Communications Lead, and Operations Lead [S32].
- README: GitHub's guidance says a README typically covers what the project does, why it is useful, how to get started, where to get help, and who maintains it, and that longer documentation belongs elsewhere (for example a wiki or docs folder) [S31]. I attempted to verify the community "Standard Readme" specification but the fetch returned no content, so it is not cited.
- Cost models: I did not find an authoritative standard template for LLM cost models. The defensible approach is to compute cost from logged token counts (OTel attributes above) times a provider price table that is dated, plus infrastructure cost, and to state volume scenarios.

LLM-specific runbook entries worth writing: provider outage (switch model alias), cost spike (check unbounded consumption, LLM10), eval regression after a prompt change (roll back prompt alias), review backlog over SLO, NHTSA ingestion failure or schema change (contract violation), forecast spike alert triage.

### 12. Forecasting and ML pipeline documentation

- Experiment tracking: MLflow Tracking organizes work into experiments and runs; each run logs parameters, metrics, code versions, and artifacts; MLflow 3 links metrics to specific models and datasets, and `mlflow.log_input()` records the datasets used [S38].
- Model registry: MLflow Model Registry provides lineage (which run produced the model), versioning, aliases (for example `@champion`), tags (for example `validation_status:approved`), and Markdown annotations per version [S39].
- Baselines: FPP3 uses four simple benchmark methods (mean, naive, seasonal naive, drift) and says any new method should be compared to them; if it does not beat them, "the new method is not worth considering" [S37].
- Backtesting: FPP3 describes time series cross-validation, also called "evaluation on a rolling forecasting origin," averaging accuracy over a series of test sets; test sets should be at least as large as the maximum forecast horizon; scaled errors such as MASE compare against the naive forecast [S37].

Implication: the backtest report should state the series (weekly complaints per component), the horizon, the rolling-origin schedule, baseline and candidate scores (MAE, MASE), how spike alerts are defined (for example, actual above the upper prediction interval) and their precision on historical data, and the MLflow run IDs and registered model version.

---

## Surprising or time-sensitive findings

1. OpenTelemetry moved all GenAI semantic conventions out of the main repository in v1.42.0 (June 2026). Older blog posts and docs pointing to `opentelemetry.io/docs/specs/semconv/gen-ai/` are stale [S23, S24].
2. Amazon Augmented AI, the reference implementation of the low-confidence human review pattern, is no longer open to new customers [S19].
3. NIST states AI RMF 1.0 is under revision [S22]; cite version and date.
4. C4's author says context and container diagrams are sufficient for most teams; component and code diagrams are optional [S7].
5. Google SRE's playbook claim (about 3x MTTR improvement) is one of the few quantified arguments for operational documentation [S36].
6. Anthropic's widely cited agents article now carries a notice that its tooling landscape has changed since December 2024 [S12].

---

## (d) Sources

| ID | Source | URL | What it says |
| --- | --- | --- | --- |
| S1 | Malte Ubl, "Design Docs at Google" | https://www.industrialempathy.com/posts/design-docs-at-google/ | Anatomy and lifecycle of Google design docs; alternatives considered and cross-cutting concerns. |
| S2 | Gergely Orosz, "Companies Using RFCs or Design Docs" | https://blog.pragmaticengineer.com/rfcs-and-design-docs/ | Public RFC templates and sections at Google, Uber, HashiCorp, Monzo, and others (secondary source). |
| S3 | Michael Nygard, "Documenting Architecture Decisions" (2011) | https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions | Original ADR format: Title, Context, Decision, Status, Consequences. |
| S4 | Microsoft Azure Well-Architected, "Maintain an ADR" | https://learn.microsoft.com/en-us/azure/well-architected/architect-role/architecture-decision-record | ADR log as append-only; record options, trade-offs, confidence, status. |
| S5 | MADR (Markdown Architectural Decision Records) | https://adr.github.io/madr/ | MADR 4.0.0 template with decision drivers, considered options, consequences, confirmation. |
| S6 | C4 model home | https://c4model.com/ | Four abstraction levels and diagram types, plus supporting diagrams. |
| S7 | C4 model, Diagrams | https://c4model.com/diagrams | Context and container diagrams are sufficient for most teams; dynamic and deployment diagrams. |
| S8 | arc42 documentation | https://docs.arc42.org/home/ | The 12 arc42 template sections and the "thorough" and "essential" tags. |
| S9 | Gebru et al., "Datasheets for Datasets" | https://arxiv.org/abs/1803.09010 | Datasheet questions by lifecycle stage: motivation through maintenance. |
| S10 | Open Data Contract Standard (Bitol) | https://bitol-io.github.io/open-data-contract-standard/latest/ | YAML data contract sections: schema, data quality, SLA, team, roles. |
| S11 | OpenLineage | https://openlineage.io/docs/ | Open standard for lineage: dataset, job, run entities and facets. |
| S12 | Anthropic, "Building effective agents" | https://www.anthropic.com/engineering/building-effective-agents | Workflows versus agents, routing to cheaper or stronger models, tool definition guidance. |
| S13 | Model Context Protocol spec, Tools (2025-06-18) | https://modelcontextprotocol.io/specification/2025-06-18/server/tools | Tool schema fields, error types, security requirements, human in the loop. |
| S14 | MLflow Prompt Registry | https://mlflow.org/docs/latest/genai/prompt-registry/ | Immutable prompt versions, commit messages, aliases for deployment and rollback. |
| S15 | Mitchell et al., "Model Cards for Model Reporting" | https://arxiv.org/abs/1810.03993 | Model card sections and disaggregated evaluation. |
| S16 | NTIA, AI System Disclosures | https://www.ntia.gov/issues/artificial-intelligence/ai-accountability-policy-report/developing-accountability-inputs-a-deeper-dive/information-flow/ai-system-disclosures | Defines datasheets, model cards, and system cards as disclosure artifacts. |
| S17 | OpenAI, Evaluation best practices | https://platform.openai.com/docs/guides/evaluation-best-practices | Eval-driven development, continuous evaluation, evaluator types, LLM-judge recommendations. |
| S18 | Zheng et al., "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena" | https://arxiv.org/abs/2306.05685 | Position, verbosity, self-enhancement biases; over 80 percent agreement with humans after mitigation. |
| S19 | AWS, Amazon Augmented AI | https://docs.aws.amazon.com/sagemaker/latest/dg/a2i-use-augmented-ai-a2i-human-review-loops.html | Human review of low-confidence or sampled predictions; service closed to new customers. |
| S20 | OWASP Threat Modeling Cheat Sheet | https://cheatsheetseries.owasp.org/cheatsheets/Threat_Modeling_Cheat_Sheet.html | Four questions, DFDs with trust boundaries, STRIDE, threat responses. |
| S21 | Microsoft Threat Modeling Tool, Threats | https://learn.microsoft.com/en-us/azure/security/develop/threat-modeling-tool-threats | STRIDE category definitions. |
| S22 | NIST AI Risk Management Framework | https://www.nist.gov/itl/ai-risk-management-framework | AI RMF 1.0 status, GenAI profile, revision notice; core functions via AIRC page https://airc.nist.gov/airmf-resources/airmf/5-sec-core/ |
| S23 | OpenTelemetry semantic conventions v1.42.0 release | https://github.com/open-telemetry/semantic-conventions/releases/tag/v1.42.0 | GenAI conventions deprecated in the main repo and moved. |
| S24 | OpenTelemetry GenAI semantic conventions repository, attribute registry | https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/registry/attributes/gen-ai.md | Current `gen_ai.*` attributes for tokens, models, tools, retrieval, prompts. |
| S25 | NIST AI 600-1, Generative AI Profile | https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf | GenAI-specific risks and actions mapped to Govern, Map, Measure, Manage. |
| S26 | OWASP Top 10 for LLM Applications 2025 | https://genai.owasp.org/llm-top-10/ | The ten 2025 risk IDs and names. |
| S27 | OWASP LLM01:2025 Prompt Injection | https://genai.owasp.org/llmrisk/llm01-prompt-injection/ | Direct and indirect injection, RAG scenario, seven mitigation strategies. |
| S28 | Microsoft, Threat Modeling AI/ML Systems and Dependencies | https://learn.microsoft.com/en-us/security/engineering/threat-modeling-aiml | Rethinking trust boundaries; data poisoning; supply chain inventory. |
| S29 | Microsoft Presidio | https://github.com/microsoft/presidio | Open-source PII detection, redaction, masking, anonymization. |
| S30 | Google SRE book, Service Level Objectives | https://sre.google/sre-book/service-level-objectives/ | SLI, SLO, SLA, and error budget definitions. |
| S31 | GitHub Docs, About READMEs | https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes | What a README should contain; longer docs belong elsewhere. |
| S32 | Google SRE workbook, Incident Response | https://sre.google/workbook/incident-response/ | Three Cs and the IC, Communications Lead, Ops Lead roles. |
| S33 | NHTSA Datasets and APIs | https://www.nhtsa.gov/nhtsa-datasets-and-apis | Complaint and recall flat files, import instructions, and recall API endpoints. |
| S34 | Microsoft HAX Toolkit, Guidelines for Human-AI Interaction | https://www.microsoft.com/en-us/haxtoolkit/ai-guidelines/ | 18 guidelines organized by interaction phase, including when the AI is wrong. |
| S35 | UK MOD, Guidance on System Cards | https://www.digital.mod.uk/policy-rules-standards-and-guidance/aiph/development/guidance-on-system-cards | System cards as single source of truth for a deployed AI system. Seen via search summary; full page not fetched. |
| S36 | Google SRE book, Introduction | https://sre.google/sre-book/introduction/ | Playbooks give roughly 3x MTTR improvement over improvising. |
| S37 | Hyndman and Athanasopoulos, Forecasting: Principles and Practice (3rd ed.), ch. 5 | https://otexts.com/fpp3/tscv.html | Benchmark methods, train/test splits, MASE, rolling-origin cross-validation. |
| S38 | MLflow Tracking | https://mlflow.org/docs/latest/ml/tracking/ | Experiments, runs, parameters, metrics, artifacts, dataset logging. |
| S39 | MLflow Model Registry | https://mlflow.org/docs/latest/ml/model-registry/ | Versioning, lineage, aliases, tags, annotations. |
