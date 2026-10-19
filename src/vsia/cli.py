"""Command line entry point: `vsia <command>`. Every pipeline stage is runnable from here."""

from __future__ import annotations

import argparse
import json
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="vsia", description="Vehicle Service Intelligence Agent")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest", help="pull complaints and recalls from the NHTSA API")
    s.add_argument("--refresh-vehicles", action="store_true")

    s = sub.add_parser("triage", help="triage one complaint or the newest untriaged ones")
    s.add_argument("--odi", type=int)
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--provider")

    s = sub.add_parser("chat", help="ask a question (RAG)")
    s.add_argument("question")
    s.add_argument("--provider")

    sub.add_parser("review", help="list pending review items")
    s = sub.add_parser("serve", help="run the HTTP API")
    s.add_argument("--port", type=int, default=8000)

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if a.cmd == "ingest":
        from vsia import ingest
        if a.refresh_vehicles:
            ingest.resolve_vehicles(refresh=True)
        for r in (ingest.ingest_complaints(), ingest.ingest_recalls()):
            print(json.dumps({k: v for k, v in r.items() if k != "details"}, default=str))
    elif a.cmd == "triage":
        from sqlalchemy import select

        from vsia import agent, db
        if a.odi:
            ids = [a.odi]
        else:
            done = select(db.triage_records.c.odi_number)
            with db.engine().begin() as conn:
                ids = [r[0] for r in conn.execute(select(db.complaints.c.odi_number)
                                                  .where(db.complaints.c.odi_number.not_in(done))
                                                  .order_by(db.complaints.c.date_filed.desc()).limit(a.limit))]
        run_id = agent.new_run_id("cli")
        for odi in ids:
            rec = agent.triage(agent.load_complaint(odi), provider=a.provider, run_id=run_id)
            print(json.dumps({"odi": odi, "component": rec.output.component, "severity": rec.output.severity,
                              "recalls": [m.campaign_number for m in rec.output.recall_matches],
                              "confidence": rec.confidence, "route": rec.route, "latency_ms": rec.latency_ms}))
    elif a.cmd == "chat":
        from vsia import rag
        print(json.dumps(rag.answer(a.question, provider=a.provider), indent=2, default=str))
    elif a.cmd == "review":
        from vsia import review
        print(review.pending().to_string())
    elif a.cmd == "serve":
        import uvicorn
        uvicorn.run("vsia.api:app", host="0.0.0.0", port=a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
