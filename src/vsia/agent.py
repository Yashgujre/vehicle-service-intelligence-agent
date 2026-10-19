"""Triage agent (FR-4, FR-5, FR-6). A fixed workflow with tool calls, not a free-running agent loop:

  complaint -> redact PII -> injection check -> tools (recall lookup + recall search) -> one LLM call with
  structured output -> validation (schema, taxonomy, citation grounding) -> severity business rule ->
  calibrated confidence -> route (auto | review) -> persist

Provider "heuristic" runs the same workflow with the TF-IDF classifier instead of an LLM; it is the
no-LLM baseline in the model comparison.
"""

from __future__ import annotations

import time
import uuid
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import insert, select

from vsia import config, confidence, db, guardrails, llm, tools
from vsia.taxonomy import normalize_component, split_components
from vsia.schemas import (
    Complaint,
    ExtractedFields,
    RecallMatch,
    TriageOutput,
    TriageRecord,
)

PROMPT_VERSION = "triage-v1"
_PROMPT_FILE = Path(__file__).parent / "prompts" / "triage_v1.md"
_GLOSSARY_FILE = config.REPO_ROOT / "config" / "component_glossary.yaml"


@lru_cache
def system_prompt() -> str:
    glossary = yaml.safe_load(_GLOSSARY_FILE.read_text())
    comp_lines = "\n".join(f"   - {c}: {glossary.get(c, '')}" for c in config.components())
    sev_lines = "\n".join(f"   - {k}: {v}" for k, v in config.severity_levels().items())
    return _PROMPT_FILE.read_text().format(component_glossary=comp_lines, severity_rubric=sev_lines)


def _candidates(c: Complaint, redacted: str, top_k: int) -> tuple[list[dict], float, list[str]]:
    """Union of the vehicle's recalls (lookup tool) and the best retrieval hits (search tool).
    Also returns the search tool's ranked campaign list, used for recall@k."""
    by_campaign: dict[str, dict] = {}
    for r in tools.recall_lookup(c.make, c.model, c.model_year):
        by_campaign[r["campaign_number"]] = {**r, "retrieval_score": 0.0}
    top_score = 0.0
    ranked_search: list[str] = []
    for h in tools.recall_search(redacted[:2000], c.make, c.model, c.model_year, top_k=top_k):
        camp = h.metadata.get("campaign_number")
        if not camp:
            continue
        if camp not in ranked_search:
            ranked_search.append(camp)
        top_score = max(top_score, float(h.score))
        entry = by_campaign.setdefault(camp, {"campaign_number": camp,
                                              "component": h.metadata.get("component"),
                                              "summary": h.text[:400], "remedy": None})
        entry["retrieval_score"] = max(entry.get("retrieval_score", 0.0), float(h.score))
    ranked = sorted(by_campaign.values(), key=lambda r: -r.get("retrieval_score", 0.0))
    return ranked[:12], top_score, ranked_search


def _user_message(c: Complaint, redacted: str, cands: list[dict]) -> str:
    cand_txt = "\n".join(
        f"- {r['campaign_number']} | component: {r.get('component') or 'n/a'} | {(r.get('summary') or '')[:300]}"
        for r in cands) or "(none)"
    return (f"Vehicle on file: {c.model_year} {c.make} {c.model}\n\n"
            f"{guardrails.wrap_untrusted(redacted, tag='complaint')}\n\n"
            f"<candidate_recalls>\n{cand_txt}\n</candidate_recalls>")


def _classifier_probs(text: str) -> dict[str, float]:
    try:
        from vsia import classifier
        return classifier.predict_proba([text])[0]
    except Exception:  # noqa: BLE001
        return {}


def _heuristic_output(c: Complaint, probs: dict[str, float], redacted: str) -> TriageOutput:
    label, p = max(probs.items(), key=lambda kv: kv[1]) if probs else ("OTHER", 0.0)
    return TriageOutput(
        extracted=ExtractedFields(make=c.make, model=c.model, model_year=c.model_year,
                                  symptom=redacted[:160]),
        component=label, severity="S3", severity_reason="heuristic baseline: no severity model",
        recall_matches=[], model_confidence=p)


def triage(c: Complaint, *, provider: str | None = None, model: str | None = None,
           run_id: str | None = None, persist: bool = True, enqueue: bool = True) -> TriageRecord:
    provider = provider or config.llm_provider()
    model_name = model or config.llm_model(provider)
    started = time.perf_counter()
    threshold = config.confidence_threshold(provider)
    top_k = config.settings()["retrieval"]["top_k"]

    red = guardrails.redact(c.summary)
    inj = guardrails.detect_injection(c.summary)
    cands, top_score, ranked_search = _candidates(c, red.text, top_k)
    allowed = {r["campaign_number"] for r in cands}
    probs = _classifier_probs(red.text)

    signals: dict = {"pii_redactions": sum(red.counts.values()), "injection_score": float(inj.score),
                     "n_candidates": len(cands), "retrieval_top_score": top_score,
                     "retrieval_ranked": ranked_search, "candidates": sorted(allowed)}
    cost = 0.0
    llm_failed = False
    if provider == "heuristic":
        out = _heuristic_output(c, probs, red.text)
    else:
        try:
            res = llm.complete_json(system_prompt(), _user_message(c, red.text, cands), TriageOutput,
                                    purpose="triage", provider=provider, model=model_name,
                                    prompt_version=PROMPT_VERSION, ref_id=str(c.odi_number))
            out = res.data
            cost = res.call.cost_usd
            signals["schema_retry"] = 1.0 if res.attempts > 1 else 0.0
        except llm.LLMError as e:
            llm_failed = True
            signals["llm_error"] = str(e)[:300]
            signals["llm_status"] = e.status
            out = _heuristic_output(c, probs, red.text)

    # Semantic validation: taxonomy membership and citation grounding.
    canon = set(config.components())
    if out.component not in canon:
        signals["component_off_taxonomy"] = out.component
        out.component = normalize_component(out.component)  # 'POWER TRAIN:DRIVELINE:...' -> 'POWER TRAIN'
    out.secondary_components = [normalize_component(s) for s in out.secondary_components]
    out.secondary_components = [s for s in dict.fromkeys(out.secondary_components)
                                if s in canon and s not in (out.component, "OTHER")][:2]
    kept = set(guardrails.validate_citations([m.campaign_number for m in out.recall_matches], allowed))
    # Grounding rule: a recall can only explain the complaint if it covers one of the triaged components.
    if config.settings()["retrieval"].get("require_component_overlap", True):
        triaged = {out.component, *out.secondary_components}
        comp_of = {r["campaign_number"]: set(split_components(r.get("component"))) for r in cands}
        kept = {cn for cn in kept if comp_of.get(cn, set()) & triaged}
    dropped = len(out.recall_matches) - len(kept)
    if dropped:
        signals["citations_dropped"] = dropped
    out.recall_matches = [m for m in out.recall_matches if m.campaign_number in kept]

    # Business rule: an owner-reported crash, fire, injury or death is always S1.
    signals["llm_severity"] = out.severity
    if c.crash or c.fire or c.injuries > 0 or c.deaths > 0:
        if out.severity != "S1":
            signals["severity_rule_override"] = True
            out.severity_reason = "owner reported crash, fire, injury or death (business rule)"
        out.severity = "S1"

    signals.update({
        "llm_confidence": float(out.model_confidence),
        "clf_prob_of_llm_label": float(probs.get(out.component, 0.0)),
        "clf_max_prob": float(max(probs.values())) if probs else 0.0,
        "clf_top_label": max(probs, key=probs.get) if probs else None,
        "agree": 1.0 if probs and max(probs, key=probs.get) == out.component else 0.0,
    })
    conf, method = confidence.score(signals, provider)
    signals["confidence_method"] = method

    reasons = []
    if inj.flagged or out.injection_suspected:
        reasons.append("possible prompt injection in complaint text")
    if llm_failed:
        reasons.append("LLM call failed or output invalid twice")
    if conf < threshold:
        reasons.append(f"confidence {conf:.3f} below threshold {threshold:.3f}")
    route = "review" if reasons else "auto"
    signals["review_reasons"] = reasons

    cited = [f"recall:{m.campaign_number}" for m in out.recall_matches] + [f"complaint:{c.odi_number}"]
    rec = TriageRecord(odi_number=c.odi_number, output=out, confidence=round(conf, 4),
                       confidence_signals=signals, route=route, cited_sources=cited, provider=provider,
                       model=model_name, prompt_version=PROMPT_VERSION,
                       latency_ms=int((time.perf_counter() - started) * 1000), cost_usd=cost)
    if persist:
        save(rec, run_id=run_id, enqueue=enqueue)
    return rec


def save(rec: TriageRecord, run_id: str | None = None, enqueue: bool = True) -> int:
    with db.engine().begin() as conn:
        res = conn.execute(insert(db.triage_records).values(
            odi_number=rec.odi_number, run_id=run_id, schema_version=rec.schema_version,
            component=rec.output.component, severity=rec.output.severity,
            recall_campaigns=[m.campaign_number for m in rec.output.recall_matches],
            confidence=rec.confidence, confidence_signals=rec.confidence_signals, route=rec.route,
            output=rec.output.model_dump(mode="json"), cited_sources=rec.cited_sources,
            provider=rec.provider, model=rec.model, prompt_version=rec.prompt_version,
            latency_ms=rec.latency_ms, cost_usd=rec.cost_usd, created_at=rec.created_at))
        rid = int(res.inserted_primary_key[0])
        if rec.route == "review" and enqueue:
            conn.execute(insert(db.review_queue).values(
                odi_number=rec.odi_number, triage_record_id=rid, status="pending",
                reason="; ".join(rec.confidence_signals.get("review_reasons", []))))
    return rid


def load_complaint(odi_number: int) -> Complaint:
    with db.engine().begin() as conn:
        row = conn.execute(select(db.complaints).where(db.complaints.c.odi_number == odi_number)).mappings().first()
    if row is None:
        raise KeyError(odi_number)
    return Complaint(**{k: row[k] for k in Complaint.model_fields if k in row})


def new_run_id(prefix: str = "triage") -> str:
    return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


__all__ = ["triage", "save", "load_complaint", "new_run_id", "system_prompt", "RecallMatch"]
