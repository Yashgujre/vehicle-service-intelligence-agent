"""Agent tools. Each tool is a plain function plus a spec (name, description, input schema) so the same
tool can be called deterministically by the Python workflow or exposed to an n8n AI Agent / MCP client.
Specs are documented in docs/llm/tools.md."""

from __future__ import annotations

import re

from sqlalchemy import select

from vsia import db, nhtsa
from vsia.schemas import RetrievalHit


def model_family(model: str | None) -> str:
    """Normalise model strings that differ between complaint and recall records
    ('MUSTANG MACH-E BEV', 'MUSTANG MACH E', 'F-150 (SUPER CREW) LIGHTNING BEV' -> 'MUSTANG MACH E', ...)."""
    try:
        from vsia.retrieval import model_family as _mf  # single source of truth when available
        return _mf(model)
    except Exception:  # noqa: BLE001
        pass
    m = (model or "").upper()
    m = re.sub(r"\(.*?\)", " ", m)
    m = re.sub(r"\b(BEV|HEV|PHEV|AWD|RWD|4WD|EARLY RELEASE|LATER RELEASE|ALL VARIANTS|\d-SEAT)\b", " ", m)
    m = m.replace("-", " ")
    return re.sub(r"\s+", " ", m).strip()


RECALL_LOOKUP_SPEC = {
    "name": "recall_lookup",
    "description": "List NHTSA recall campaigns that cover a specific vehicle (make, model, model year). "
                   "Returns campaign number, component, report date, summary and remedy. Read-only.",
    "input_schema": {"type": "object", "required": ["make", "model", "model_year"],
                     "properties": {"make": {"type": "string"}, "model": {"type": "string"},
                                    "model_year": {"type": "integer"}}},
}


def recall_lookup(make: str, model: str, model_year: int, live: bool = False) -> list[dict]:
    """Recalls for one vehicle. Reads the local recalls table (refreshed daily by ingestion) so evaluation
    is reproducible; `live=True` also queries the NHTSA API and merges new campaigns."""
    fam = model_family(model)
    with db.engine().begin() as conn:
        rows = conn.execute(select(db.recalls).where(db.recalls.c.make == make.upper(),
                                                     db.recalls.c.model_year == int(model_year))).mappings().all()
    out = {r["campaign_number"]: dict(r) for r in rows if model_family(r["model"]) == fam}
    if live:
        try:
            for raw in nhtsa.recalls_by_vehicle(make, model, model_year):
                rec = nhtsa.normalize_recall(raw)
                out.setdefault(rec["campaign_number"], rec)
        except Exception:  # noqa: BLE001
            pass
    return [{"campaign_number": c, "component": r.get("component_raw") or r.get("component_primary"),
             "summary": r.get("summary"), "remedy": r.get("remedy"),
             "report_date": str(r.get("report_date") or "")} for c, r in out.items()]


RECALL_SEARCH_SPEC = {
    "name": "recall_search",
    "description": "Semantic + keyword search over recall records and parsed recall documents, filtered to "
                   "the vehicle. Use the complaint's symptom description as the query. Read-only.",
    "input_schema": {"type": "object", "required": ["query", "make", "model_year"],
                     "properties": {"query": {"type": "string"}, "make": {"type": "string"},
                                    "model": {"type": "string"}, "model_year": {"type": "integer"},
                                    "top_k": {"type": "integer", "default": 5}}},
}


def recall_search(query: str, make: str, model: str, model_year: int, top_k: int = 5) -> list[RetrievalHit]:
    try:
        from vsia.retrieval import search_recalls_for_complaint
    except Exception:  # noqa: BLE001
        return []
    try:
        return search_recalls_for_complaint(make=make, model=model, model_year=model_year, text=query, top_k=top_k)
    except Exception:  # noqa: BLE001
        return []
