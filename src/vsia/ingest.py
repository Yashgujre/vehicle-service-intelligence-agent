"""Ingestion (FR-1): resolve the scoped vehicles, pull complaints and recalls from the NHTSA API,
and load them idempotently. Duplicate complaint IDs are skipped, never overwritten, and every run
writes a row to ingestion_runs with fetched / inserted / duplicate / filtered counts."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime

from sqlalchemy import delete, insert, select

from vsia import db, nhtsa
from vsia.config import DATA_DIR, settings
from vsia.taxonomy import primary_component

log = logging.getLogger(__name__)
VEHICLES_FILE = DATA_DIR / "raw" / "scoped_vehicles.json"


def resolve_vehicles(refresh: bool = False) -> list[dict]:
    """Return [{make, model, model_year}] for the configured segment, using NHTSA's own model strings.
    Cached to data/raw/scoped_vehicles.json so daily runs do not re-resolve."""
    if VEHICLES_FILE.exists() and not refresh:
        return json.loads(VEHICLES_FILE.read_text())
    seg = settings()["segment"]
    out: list[dict] = []
    for v in seg["vehicles"]:
        pats = [re.compile(p, re.I) for p in v["patterns"]]
        for year in seg["model_years"]:
            try:
                names = set(nhtsa.models_for(v["make"], year, "c")) | set(nhtsa.models_for(v["make"], year, "r"))
            except Exception as e:  # noqa: BLE001
                log.warning("model lookup failed %s %s: %s", v["make"], year, e)
                names = set()
            candidates = {n for n in names if any(p.search(n) for p in pats)} | set(v.get("aliases", []))
            for model in sorted(candidates):
                out.append({"make": v["make"], "model": model, "model_year": year})
            time.sleep(0.1)
    VEHICLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    VEHICLES_FILE.write_text(json.dumps(out, indent=1))
    return out


def _existing_ids(conn) -> set[int]:
    return {r[0] for r in conn.execute(select(db.complaints.c.odi_number))}


def ingest_complaints(vehicles: list[dict] | None = None, source: str = "api") -> dict:
    """Pull complaints for every scoped vehicle. Safe to re-run: existing ODI numbers are skipped."""
    started = datetime.utcnow()
    vehicles = vehicles or resolve_vehicles()
    filed_from = date.fromisoformat(settings()["segment"]["filed_from"])
    excluded = {m.upper() for m in settings()["segment"].get("exclude_models", [])}
    fetched = inserted = dup = filtered = 0
    per_vehicle: dict[str, int] = {}
    failed_vehicles: list[str] = []
    purged = 0
    error = None
    eng = db.engine()
    try:
        with eng.begin() as conn:
            # Exclusions added to config after a load also apply to rows already stored (ADR-0004).
            purged = conn.execute(delete(db.complaints).where(db.complaints.c.model.in_(excluded))).rowcount \
                if excluded else 0
            seen = _existing_ids(conn)
        for v in vehicles:
            try:
                rows = nhtsa.complaints_by_vehicle(v["make"], v["model"], v["model_year"])
            except Exception as e:  # noqa: BLE001
                log.warning("complaints fetch failed %s: %s", v, e)
                failed_vehicles.append(f"{v['make']}|{v['model']}|{v['model_year']}: {type(e).__name__}")
                continue
            fetched += len(rows)
            batch = []
            for raw in rows:
                rec = nhtsa.normalize_complaint(raw, v["make"], v["model"], v["model_year"])
                if rec["odi_number"] in seen:
                    dup += 1
                    continue
                if (not rec["summary"] or rec["model"] in excluded
                        or (rec["date_filed"] and rec["date_filed"] < filed_from)):
                    filtered += 1
                    continue
                rec["component_primary"] = primary_component(rec["components_raw"])
                rec["source"] = source
                seen.add(rec["odi_number"])
                batch.append(rec)
            if batch:
                with eng.begin() as conn:
                    conn.execute(insert(db.complaints), batch)
            inserted += len(batch)
            if rows:
                per_vehicle[f"{v['make']}|{v['model']}|{v['model_year']}"] = len(rows)
            time.sleep(0.15)
    except Exception as e:  # noqa: BLE001
        error = repr(e)
    result = {
        "kind": f"complaints_{source}",
        "started_at": started,
        "finished_at": datetime.utcnow(),
        "rows_fetched": fetched,
        "rows_inserted": inserted,
        "rows_skipped_duplicate": dup,
        "rows_filtered": filtered,
        "ok": error is None and not failed_vehicles,
        "error": error or (f"{len(failed_vehicles)} vehicle fetch(es) failed" if failed_vehicles else None),
        "details": {"per_vehicle": per_vehicle, "failed_vehicles": failed_vehicles,
                    "rows_purged_excluded_models": purged},
    }
    with eng.begin() as conn:
        conn.execute(insert(db.ingestion_runs).values(**result))
    log.info("complaints run: %s", {k: v for k, v in result.items() if k != "details"})
    return result


def recall_vehicles() -> list[dict]:
    """Recall model strings differ from complaint query strings ('MUSTANG MACH E' vs 'MUSTANG MACH-E BEV').
    The canonical names stored from complaint product records work for the recall API, so query every
    distinct (make, model, year) present in complaints, plus the resolved segment strings as a fallback."""
    with db.engine().begin() as conn:
        rows = conn.execute(select(db.complaints.c.make, db.complaints.c.model, db.complaints.c.model_year)
                            .distinct()).all()
    seen = {(r.make, r.model, r.model_year) for r in rows}
    for v in resolve_vehicles():
        seen.add((v["make"], v["model"].upper(), v["model_year"]))
    return [{"make": m, "model": mo, "model_year": y} for m, mo, y in sorted(seen)]


def ingest_recalls(vehicles: list[dict] | None = None) -> dict:
    started = datetime.utcnow()
    vehicles = vehicles or recall_vehicles()
    eng = db.engine()
    fetched = inserted = dup = 0
    with eng.begin() as conn:
        seen = {
            (r.campaign_number, r.make, r.model, r.model_year)
            for r in conn.execute(select(db.recalls.c.campaign_number, db.recalls.c.make,
                                         db.recalls.c.model, db.recalls.c.model_year))
        }
    for v in vehicles:
        try:
            rows = nhtsa.recalls_by_vehicle(v["make"], v["model"], v["model_year"])
        except Exception as e:  # noqa: BLE001
            log.warning("recalls fetch failed %s: %s", v, e)
            continue
        fetched += len(rows)
        batch = []
        for raw in rows:
            rec = nhtsa.normalize_recall(raw)
            key = (rec["campaign_number"], rec["make"], rec["model"], rec["model_year"])
            if key in seen:
                dup += 1
                continue
            seen.add(key)
            rec["component_primary"] = primary_component(rec["component_raw"])
            batch.append(rec)
        if batch:
            with eng.begin() as conn:
                conn.execute(insert(db.recalls), batch)
        inserted += len(batch)
        time.sleep(0.15)
    result = {
        "kind": "recalls",
        "started_at": started,
        "finished_at": datetime.utcnow(),
        "rows_fetched": fetched,
        "rows_inserted": inserted,
        "rows_skipped_duplicate": dup,
        "rows_filtered": 0,
        "ok": True,
        "error": None,
        "details": {},
    }
    with eng.begin() as conn:
        conn.execute(insert(db.ingestion_runs).values(**result))
    return result
