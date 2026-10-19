"""HTTP service that n8n, Open WebUI and the dashboard call. Run: uvicorn vsia.api:app --port 8000"""

from __future__ import annotations

import hmac
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from vsia import agent, config, db, guardrails, ingest, review
from vsia.schemas import Complaint, ReviewDecision

app = FastAPI(title="Vehicle Service Intelligence Agent", version="0.1.0")


def auth(authorization: str | None = Header(default=None)) -> None:
    """Bearer token (VSIA_API_TOKEN). Unset means local development without auth; the compose deployment
    refuses to start without it."""
    token = os.getenv("VSIA_API_TOKEN")
    if token and not hmac.compare_digest((authorization or "").encode(), f"Bearer {token}".encode()):
        raise HTTPException(status_code=401, detail="invalid token")


class TriageRequest(BaseModel):
    odi_number: int | None = None
    complaint: Complaint | None = None
    provider: str | None = None


class BatchRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)
    provider: str | None = None


class ChatRequest(BaseModel):
    question: str = Field(max_length=2000)
    provider: str | None = None


@app.get("/health")
def health() -> dict:
    with db.engine().begin() as conn:
        conn.execute(text("select 1"))
    return {"ok": True, "llm_provider": config.llm_provider(), "llm_model": config.llm_model(),
            "vector_store": config.env().vsia_vector_store, "threshold": config.confidence_threshold()}


@app.post("/triage", dependencies=[Depends(auth)])
def triage_one(req: TriageRequest) -> dict:
    if req.complaint is None and req.odi_number is None:
        raise HTTPException(400, "send odi_number or complaint")
    c = req.complaint or agent.load_complaint(req.odi_number)
    rec = agent.triage(c, provider=req.provider, run_id=agent.new_run_id("api"))
    return rec.model_dump(mode="json")


@app.post("/triage/pending", dependencies=[Depends(auth)])
def triage_pending(req: BatchRequest) -> dict:
    """Triage complaints that have no production triage record yet (newest first). Called by n8n after
    ingestion. Evaluation runs (run_id 'eval-...') do not count as production triage (ADR-0064)."""
    done = select(db.triage_records.c.odi_number).where(
        db.triage_records.c.run_id.is_(None) | db.triage_records.c.run_id.not_like("eval-%"))
    q = (select(db.complaints.c.odi_number).where(db.complaints.c.odi_number.not_in(done))
         .order_by(db.complaints.c.date_filed.desc()).limit(req.limit))
    with db.engine().begin() as conn:
        ids = [r[0] for r in conn.execute(q)]
    run_id = agent.new_run_id("batch")
    routes = {"auto": 0, "review": 0}
    for odi in ids:
        rec = agent.triage(agent.load_complaint(odi), provider=req.provider, run_id=run_id)
        routes[rec.route] += 1
    return {"run_id": run_id, "triaged": len(ids), **routes}


@app.post("/ingest/daily", dependencies=[Depends(auth)])
def ingest_daily() -> dict:
    c = ingest.ingest_complaints()
    r = ingest.ingest_recalls()
    strip = lambda d: {k: v for k, v in d.items() if k not in ("details", "started_at", "finished_at")}  # noqa: E731
    return {"complaints": strip(c), "recalls": strip(r)}


@app.get("/review/pending", dependencies=[Depends(auth)])
def review_pending(limit: int = Query(default=50, ge=1, le=500)) -> list[dict]:
    return review.pending(limit).to_dict(orient="records")


@app.post("/review/decision", dependencies=[Depends(auth)])
def review_decision(d: ReviewDecision) -> dict:
    try:
        return review.decide(d)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/search", dependencies=[Depends(auth)])
def search(q: str = Query(max_length=2000), namespace: str | None = None, make: str | None = None,
           model: str | None = None, model_year: int | None = None,
           top_k: int = Query(default=5, ge=1, le=50)) -> list[dict]:
    """Retrieval as a tool (n8n-native agent variant, debugging). With make, model and model_year and no
    namespace it runs the agent's own recall search (vehicle-filtered, campaign-deduplicated)."""
    from vsia import retrieval, tools
    text_q = guardrails.redact(q).text
    if namespace is None and make and model and model_year:
        hits = tools.recall_search(text_q, make, model, model_year, top_k=top_k)
    else:
        ns = namespace or "recalls"
        flt: dict = {"make": make.upper()} if make else {}
        if model:
            flt["model_family"] = retrieval.model_family(model)
        if model_year:
            flt["model_years" if ns == "recall_docs" else "model_year"] = model_year
        if ns == "recall_docs" and "model_family" in flt:
            flt["models"] = flt.pop("model_family")
        hits = retrieval.get_store().search(ns, text_q, top_k=top_k, filter=flt)
    return [h.model_dump() for h in hits]


@app.post("/chat", dependencies=[Depends(auth)])
def chat(req: ChatRequest) -> dict:
    from vsia import rag
    return rag.answer(req.question, provider=req.provider)


@app.post("/forecast/run", dependencies=[Depends(auth)])
def forecast_run(force: bool = False) -> dict:
    """Weekly retrain (skipped when the data fingerprint is unchanged) plus spike detection.
    Returns the alerts so the n8n workflow can branch on them."""
    from pipelines import forecast
    try:
        trained = forecast.cmd_train(force=force)
        det = forecast.cmd_detect()
    except SystemExit as e:  # pipeline signals "cannot run yet" with SystemExit
        raise HTTPException(409, str(e)) from e
    alerts = det["alerts"]
    rows = [] if alerts is None or not len(alerts) else [
        {"component": r.component, "week": str(r.week.date()), "actual": float(r.actual),
         "upper": float(r.upper), "ratio": float(r.ratio), "current": bool(r.current)}
        for r in alerts.itertuples()]
    return {"run_id": det["run_id"], "retrained": trained is not None, "alerts": rows,
            "current_alerts": sum(a["current"] for a in rows)}
