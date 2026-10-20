# System card: Vehicle Service Intelligence Agent (hosted demo)

Describes the AI system as deployed, several models working together, rather than one model. The structure
is convention (NTIA AI system disclosures and UK MOD system-card guidance; see
docs/research/01_documentation_process_research.md, "System cards"). The forecaster has its own
[model card](model-card-forecaster.md).

**Status on 2026-10-20.** Deployed on Streamlit Community Cloud with data bundle `demo-data-v2` (ADR-0091).
Evaluation numbers come from `eval/run_eval.py` on the 200-complaint gold split, scored against silver
labels ([model comparison](../evaluation/model-comparison.md)).

## 1. What the system does

For one owner complaint about a vehicle defect, the triage agent returns the failed component (one of 24
NHTSA-derived classes), a severity from S1 to S4 with a reason, recall campaigns that explain it, extracted
fields and a calibrated confidence. Confident results are routed automatically; uncertain ones go to a
human review queue. A chat page answers questions about the complaints and recalls with citations. Weekly
volume forecasts and spike alerts are precomputed.

The agent is a fixed workflow, not a free-running loop (ADR-0060): redact PII, check for prompt injection,
call two recall tools, make one structured-output LLM call, validate taxonomy and citations, apply the
severity business rule, score confidence, route.

## 2. Components

| Part | Component | Notes |
|---|---|---|
| Main LLM (shared key) | Google `gemini-3.5-flash-lite`, free tier | 500 requests per day per project; the app caps itself at 400 (ADR-0092) |
| Backup LLMs (shared key) | `gemini-3.1-flash-lite`, then Groq `openai/gpt-oss-20b` | Used only when the model before them is rate limited or overloaded (ADR-0093) |
| Visitor's own key | Gemini, Groq, OpenAI or Anthropic | Kept in the browser session only, never stored or logged (ADR-0092) |
| Offline classifier | TF-IDF and logistic regression (`tfidf-logreg`) | No AI call; also the fallback when every LLM fails, and one of the confidence signals (ADR-0043) |
| Local LLM (development only) | Ollama `qwen2.5:3b` | Not available on the hosted demo |
| Embeddings | `nomic-embed-text` v1.5, in-process with fastembed | Same vectors as the Ollama model used to build the index (ADR-0090) |
| Retrieval | Hybrid dense and BM25 over recalls, recall documents and complaints | ADR-0030 |
| Confidence | Logistic calibrator per provider over six signals | ADR-0061; fitted on the 300-complaint calibration split |

## 3. Data

Public NHTSA data: 10,303 owner complaints filed 2022-01-02 to 2026-10-15 for 8 makes, 407 recall rows (200
campaigns) and 150 recall PDFs ([corpus datasheet](../data/datasheet-nhtsa-corpus.md)). Complaints are
unverified owner reports. Narratives are redacted before any model, index or log sees them; 75 narratives
contain personal details ([PII handling](../security/pii-handling.md)).

## 4. Evaluation

Gold split, 200 complaints, labels derived from NHTSA's own coding and keyword rules (silver), not from a
person reading the complaint ([gold-set datasheet](../data/datasheet-gold-set.md)).

| Metric | Gemini `gemini-3.5-flash-lite` | Offline classifier | Ollama `qwen2.5:3b` |
|---|---|---|---|
| Primary component accuracy | 0.535 | 0.555 | 0.405 |
| Any-label component accuracy | 0.700 | 0.680 | 0.520 |
| Raw S1 recall, before the business rule | 0.800 | 0.000 | 0.160 |
| Auto-routed share (accuracy) | 44% (0.875) | 19% (0.895) | 27.5% (0.964) |
| Recall citations that hit a known recall | 49.3% | 0% | 38.7% |
| Median latency per complaint | 1.5 s | 0.08 s | 33 s |
| Failure rate | 0 | 0 | 1% |

Reading the results:

- On component accuracy against NHTSA's coding, no LLM beats the TF-IDF baseline. Gemini adds severity
  judgement, recall linking with citations and more cases routed without review.
- The design targets of 85% component accuracy and 70% auto-routed are not met (design doc G4, G5).
- Retrieval finds a known recall in the top 5 for 81.3% of the 75 gold complaints that have one.

Not evaluated: the backup models and Groq (they reuse the main model's calibrator or the default threshold),
chat answer quality, per-make or per-component slices, and hand-labelled agreement
([labeling guide](../evaluation/labeling-guide.md)).

## 5. Safeguards

| Risk | Safeguard |
|---|---|
| Personal data reaching a model or log | Regex redaction before every model call, embedding and log (ADR-0020, ADR-0021) |
| Prompt injection in complaint text | Detector, untrusted-text wrapping, model self-report; any hit forces human review ([guardrails](../security/guardrails.md)) |
| Invented recalls or citations | The agent may cite only recalls its tools returned for that vehicle with an overlapping component; chat citations the sources do not support are removed (ADR-0063) |
| Under-rating a safety complaint | An owner-reported crash, fire, injury or death always gives S1 (ADR-0062) |
| Over-trusting automated results | Calibrated threshold per provider; hard overrides to review; review decisions become labels ([review workflow](../hitl/review-workflow.md)) |
| Model failure | Falls back to the offline classifier and human review; on the shared key, a chain of backup models first (ADR-0093) |
| Abuse of the shared key | 15 AI calls per session and 400 per model per day (ADR-0092) |

Threats and open risks: [threat model](../security/threat-model.md), [AI risk register](../security/ai-risk-register.md).

## 6. Intended use and limits

**Intended:** a demonstration of defect-intelligence triage for vehicle quality and service teams on public
data, where a person reviews uncertain cases.

**Not intended:**
- Safety, recall or warranty decisions without human review.
- Diagnosing a specific vehicle.
- Reading the accuracy numbers as expert-level accuracy: they measure agreement with NHTSA intake coding.

**Known limits:**
- Free-tier models can be rate limited or overloaded. On 2026-10-19 several free Gemini models returned 503
  for an evening, and the main model's daily quota ran out (ADR-0093).
- The hosted data is as old as the last bundle.
- Gold accuracy is not production-mix accuracy, because the gold split caps each class.

## 7. Change log

| Date | Change |
|---|---|
| 2026-10-19 | Hosted demo deployed; Gemini calibrator fitted (threshold 0.775) |
| 2026-10-19 | Backup model chain and Groq added to the shared key (ADR-0093) |
| 2026-10-20 | Gemini gold evaluation completed (200 of 200) |
