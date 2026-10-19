"""Human-in-the-loop review (FR-5). Low-confidence triage records wait in review_queue; an analyst accepts
or corrects them; every decision becomes a row in labels (source='review') that evaluation reuses."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import insert, select, update

from vsia import db
from vsia.guardrails import redact
from vsia.schemas import ReviewDecision


def pending(limit: int = 50) -> pd.DataFrame:
    q = (select(db.review_queue.c.id.label("queue_id"), db.review_queue.c.odi_number, db.review_queue.c.reason,
                db.review_queue.c.created_at, db.triage_records.c.id.label("triage_record_id"),
                db.triage_records.c.component, db.triage_records.c.severity,
                db.triage_records.c.recall_campaigns, db.triage_records.c.confidence,
                db.triage_records.c.provider, db.complaints.c.make, db.complaints.c.model,
                db.complaints.c.model_year, db.complaints.c.summary)
         .join(db.triage_records, db.triage_records.c.id == db.review_queue.c.triage_record_id)
         .join(db.complaints, db.complaints.c.odi_number == db.review_queue.c.odi_number)
         .where(db.review_queue.c.status == "pending")
         .order_by(db.triage_records.c.confidence.asc())
         .limit(limit))
    with db.engine().begin() as conn:
        df = pd.DataFrame(conn.execute(q).mappings().all())
    if len(df):
        df["summary"] = df["summary"].map(lambda s: redact(s or "").text)
    return df


def decide(d: ReviewDecision) -> dict:
    """Resolve the given queue item (or the oldest pending one for this complaint) and store the label."""
    where = [db.review_queue.c.odi_number == d.odi_number, db.review_queue.c.status == "pending"]
    if d.queue_id is not None:
        where.append(db.review_queue.c.id == d.queue_id)
    with db.engine().begin() as conn:
        item = conn.execute(select(db.review_queue, db.triage_records.c.component, db.triage_records.c.severity,
                                   db.triage_records.c.recall_campaigns)
                            .join(db.triage_records, db.triage_records.c.id == db.review_queue.c.triage_record_id)
                            .where(*where)
                            .order_by(db.review_queue.c.created_at)).mappings().first()
        if item is None:
            raise KeyError(f"no pending review for complaint {d.odi_number}")
        component = item["component"] if d.accepted else (d.component or item["component"])
        severity = item["severity"] if d.accepted else (d.severity or item["severity"])
        campaigns = item["recall_campaigns"] if d.accepted else (d.recall_campaigns or [])
        status = "accepted" if d.accepted else "corrected"
        conn.execute(update(db.review_queue).where(db.review_queue.c.id == item["id"])
                     .values(status=status, resolved_at=datetime.utcnow()))
        conn.execute(insert(db.labels).values(odi_number=d.odi_number, component=component, severity=severity,
                                              recall_campaigns=campaigns, source="review",
                                              reviewer=d.reviewer, note=d.note))
    return {"odi_number": d.odi_number, "status": status, "component": component, "severity": severity,
            "recall_campaigns": campaigns}


def stats() -> dict:
    with db.engine().begin() as conn:
        rows = conn.execute(select(db.review_queue.c.status)).all()
    s = pd.Series([r[0] for r in rows], dtype="object")
    return s.value_counts().to_dict() if len(s) else {}
