"""Build the retrieval index (FR-3) from the database.

    python scripts/build_index.py                      # all namespaces, store from VSIA_VECTOR_STORE
    python scripts/build_index.py --namespaces recalls recall_docs --reset

Namespaces and record design (ADR-0033):
  recalls      one record per campaign x vehicle (API rows): component + summary + consequence + remedy.
  recall_docs  chunks (about 800 tokens, 100 overlap) of the redacted markdown of parsed Part 573 reports and
               owner letters; vehicle_keys from the campaign's API rows plus the Part 573 vehicle list.
  complaints   one record per complaint: the redacted narrative only. NHTSA component labels are never
               indexed (they are the triage ground truth, ADR-0005).

Every record carries vehicle_keys ('MAKE|MODELFAMILY|YEAR') so one exact-match filter scopes a search to a
vehicle in both stores.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import select  # noqa: E402

from vsia import db  # noqa: E402
from vsia.guardrails import redact  # noqa: E402
from vsia.retrieval import LocalStore, chunk_markdown, get_store, model_family, vehicle_key  # noqa: E402


def _rows(table):
    with db.engine().connect() as conn:
        return [dict(r._mapping) for r in conn.execute(select(table))]


def recall_records() -> list[dict]:
    out = []
    for r in _rows(db.recalls):
        key = vehicle_key(r["make"], r["model"], r["model_year"])
        text = "\n".join(x for x in (
            f"Recall {r['campaign_number']} ({r['component_primary']}): {r['make']} {r['model']} {r['model_year']}",
            f"Summary: {r['summary'] or ''}", f"Consequence: {r['consequence'] or ''}",
            f"Remedy: {r['remedy'] or ''}") if x)
        out.append({
            "id": f"{r['campaign_number']}:{key}", "text": text, "campaign_number": r["campaign_number"],
            "make": r["make"], "model": r["model"], "model_year": r["model_year"],
            "model_family": model_family(r["model"]), "component": r["component_primary"],
            "component_raw": r["component_raw"], "report_date": str(r["report_date"] or ""),
            "doc_type": "api_recall", "vehicle_keys": [key],
            "source_url": f"https://www.nhtsa.gov/recalls?nhtsaId={r['campaign_number']}",
        })
    return out


def recall_doc_records() -> list[dict]:
    keys_by_campaign: dict[str, set[str]] = defaultdict(set)
    make_by_campaign: dict[str, str] = {}
    component_by_campaign: dict[str, str] = {}
    for r in _rows(db.recalls):
        keys_by_campaign[r["campaign_number"]].add(vehicle_key(r["make"], r["model"], r["model_year"]))
        make_by_campaign[r["campaign_number"]] = r["make"]
        component_by_campaign[r["campaign_number"]] = r["component_primary"]
    out = []
    for d in _rows(db.recall_documents):
        camp = d["campaign_number"]
        ext = d["extraction"] or {}
        keys = set(keys_by_campaign.get(camp, set()))
        make = make_by_campaign.get(camp)
        if make and d["doc_type"] == "RCLRPT":
            for m in ext.get("affected_models") or []:
                for y in ext.get("model_years") or []:
                    keys.add(vehicle_key(make, m, y))
        for ch in chunk_markdown(d["markdown"] or ""):
            out.append({
                "id": f"{camp}:{d['doc_type']}:{ch['chunk_index']}",
                "text": f"{d['doc_type']} {camp}: {ch['text']}", "campaign_number": camp, "make": make,
                "models": sorted({k.split('|')[1] for k in keys}), "model_years": sorted({k.split('|')[2] for k in keys}),
                "component": ext.get("component") or component_by_campaign.get(camp), "doc_type": d["doc_type"],
                "source_url": d["source_url"], "page": ch["page"], "chunk_index": ch["chunk_index"],
                "vehicle_keys": sorted(keys),
            })
    return out


def complaint_records() -> list[dict]:
    out = []
    for c in _rows(db.complaints):
        text = redact(c["summary"] or "").text.strip()
        if not text:
            continue
        key = vehicle_key(c["make"], c["model"], c["model_year"])
        out.append({
            "id": str(c["odi_number"]), "text": text, "odi_number": c["odi_number"], "make": c["make"],
            "model": c["model"], "model_year": c["model_year"], "model_family": model_family(c["model"]),
            "date_filed": str(c["date_filed"] or ""), "crash": bool(c["crash"]), "fire": bool(c["fire"]),
            "vehicle_keys": [key],
        })
    return out


BUILDERS = {"recalls": recall_records, "recall_docs": recall_doc_records, "complaints": complaint_records}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--namespaces", nargs="+", default=list(BUILDERS), choices=list(BUILDERS))
    ap.add_argument("--reset", action="store_true", help="drop the local namespace before building")
    ap.add_argument("--store", choices=["local", "pinecone"], default=None)
    a = ap.parse_args(argv)
    store = get_store(a.store)
    summary = {"store": store.name, "namespaces": {}}
    for ns in a.namespaces:
        t0 = time.perf_counter()
        recs = BUILDERS[ns]()
        if a.reset and isinstance(store, LocalStore):
            store.reset(ns)
        last = [0.0]

        def progress(done: int, total: int, ns=ns, last=last):
            if time.perf_counter() - last[0] > 15 or done == total:
                last[0] = time.perf_counter()
                print(f"  {ns}: embedded {done}/{total}", flush=True)

        n = store.upsert(ns, recs, progress=progress) if isinstance(store, LocalStore) else store.upsert(ns, recs)
        summary["namespaces"][ns] = {"records": n, "seconds": round(time.perf_counter() - t0, 1)}
        print(f"{ns}: {n} records in {summary['namespaces'][ns]['seconds']} s", flush=True)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
