"""Download recall document PDFs for in-scope campaigns (FR-2 input).

For each selected campaign, the unofficial NHTSA endpoint
  GET https://api.nhtsa.gov/safetyIssues/byNhtsaId?filter=recalls&nhtsaId=<campaign>
lists associatedDocuments with direct static.nhtsa.gov URLs. We keep:
  RCLRPT  the latest Part 573 defect report (the structured parse input), and
  RCONL   the earliest substantive owner notification letter (Part 577), when it is under 1 MB.
Files over 3 MB are skipped (checked from the listed size and again after download). Requests are throttled to about 3 per
second with retry and backoff. A manifest (campaign, doc type, url, bytes, sha256) is written to
data/docs/manifest.json.

Campaign selection: rank campaigns by the number of in-scope complaints filed on the vehicles they cover
(make + model family + model year), then round-robin across recall components so the sample spans
components rather than only the most-complained-about electrical recalls.

Usage: python scripts/fetch_recall_docs.py [--limit 80]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from vsia.config import DATA_DIR
from vsia.db import complaints, engine, recalls
from vsia.retrieval import vehicle_key

DOCS_DIR = DATA_DIR / "docs"
PDF_DIR = DOCS_DIR / "pdf"
MANIFEST = DOCS_DIR / "manifest.json"
SAFETY_ISSUES = "https://api.nhtsa.gov/safetyIssues/byNhtsaId"
MAX_BYTES = 3_000_000
MAX_LETTER_BYTES = 1_000_000
MIN_BYTES = 5_000
MIN_INTERVAL_S = 1 / 3

_client = httpx.Client(timeout=60.0, follow_redirects=True,
                       headers={"User-Agent": "vsia/0.1 (research project)"})
_last = 0.0


def _throttle() -> None:
    global _last
    wait = MIN_INTERVAL_S - (time.monotonic() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


@retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=1, max=20), reraise=True,
       retry=retry_if_exception(_retryable))
def _get(url: str, **params) -> httpx.Response:
    _throttle()
    r = _client.get(url, params=params or None)
    r.raise_for_status()
    return r


def select_campaigns(limit: int) -> list[dict]:
    with engine().connect() as conn:
        cmpl = conn.execute(select(complaints.c.make, complaints.c.model, complaints.c.model_year)).all()
        rows = conn.execute(select(recalls.c.campaign_number, recalls.c.make, recalls.c.model,
                                   recalls.c.model_year, recalls.c.component_primary)).all()
    volume: dict[str, int] = defaultdict(int)
    for make, model, year in cmpl:
        volume[vehicle_key(make, model, year)] += 1
    camp: dict[str, dict] = {}
    for c, make, model, year, comp in rows:
        d = camp.setdefault(c, {"campaign_number": c, "component": comp or "OTHER", "complaints": 0,
                                "vehicles": []})
        k = vehicle_key(make, model, year)
        if k not in d["vehicles"]:
            d["vehicles"].append(k)
            d["complaints"] += volume.get(k, 0)
    by_comp: dict[str, list[dict]] = defaultdict(list)
    for d in sorted(camp.values(), key=lambda d: (-d["complaints"], d["campaign_number"])):
        by_comp[d["component"]].append(d)
    # Round-robin: components ordered by their best campaign's complaint volume.
    order = sorted(by_comp, key=lambda c: -by_comp[c][0]["complaints"])
    picked: list[dict] = []
    while len(picked) < limit and any(by_comp.values()):
        for comp in order:
            if by_comp[comp] and len(picked) < limit:
                picked.append(by_comp[comp].pop(0))
    return picked


def doc_bytes(d: dict) -> int:
    """fileSize is in bytes for older documents but in KiB for documents loaded from about 2025 on
    (RCLRPT-25V835-8745.pdf reports 375 and is 383,967 bytes). No real PDF is under 10 KB, so small
    values are read as KiB."""
    size = int(d.get("fileSize") or 0)
    return size * 1024 if 0 < size < 10_000 else size


def choose_documents(docs: list[dict]) -> list[dict]:
    def prefix(d):
        return (d.get("fileName") or "").split("-")[0].upper()

    usable = [d for d in docs if MIN_BYTES <= doc_bytes(d) <= MAX_BYTES and d.get("url")]
    reports = sorted([d for d in usable if prefix(d) == "RCLRPT"], key=lambda d: d.get("loadDate") or "")
    letters = sorted([d for d in usable if prefix(d) == "RCONL" and doc_bytes(d) <= MAX_LETTER_BYTES],
                     key=lambda d: d.get("loadDate") or "")
    out = []
    if reports:
        out.append({**reports[-1], "doc_type": "RCLRPT"})  # latest amendment of the Part 573 report
    if letters:
        out.append({**letters[0], "doc_type": "RCONL"})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=80)
    args = ap.parse_args()
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    manifest: list[dict] = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else []
    have = {(m["campaign_number"], m["doc_type"]) for m in manifest}

    picked = select_campaigns(args.limit)
    print(f"selected {len(picked)} campaigns across {len({p['component'] for p in picked})} components")
    started = time.perf_counter()
    stats = defaultdict(int)
    for i, p in enumerate(picked, 1):
        c = p["campaign_number"]
        try:
            data = _get(SAFETY_ISSUES, filter="recalls", nhtsaId=c).json()
            rc = ((data.get("results") or [{}])[0].get("recalls") or [{}])[0]
            docs = rc.get("associatedDocuments") or []
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(picked)}] {c}: safetyIssues failed: {type(e).__name__}: {e}")
            stats["lookup_failed"] += 1
            continue
        chosen = choose_documents(docs)
        if not chosen:
            stats["no_usable_docs"] += 1
        for d in chosen:
            if (c, d["doc_type"]) in have:
                stats["already_present"] += 1
                continue
            path = PDF_DIR / d["fileName"]
            try:
                r = _get(d["url"])
            except Exception as e:  # noqa: BLE001
                print(f"  {d['fileName']}: download failed: {type(e).__name__}: {e}")
                stats["download_failed"] += 1
                continue
            body = r.content
            if len(body) > MAX_BYTES:
                stats["skipped_too_large"] += 1
                continue
            path.write_bytes(body)
            manifest.append({
                "campaign_number": c, "doc_type": d["doc_type"], "url": d["url"], "file": str(path.name),
                "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                "load_date": d.get("loadDate"), "component": p["component"],
                "complaint_volume": p["complaints"],
                "downloaded_at": datetime.now(timezone.utc).isoformat(),
            })
            have.add((c, d["doc_type"]))
            stats[f"downloaded_{d['doc_type']}"] += 1
        print(f"[{i}/{len(picked)}] {c} {p['component']}: {[d['doc_type'] for d in chosen]}")
        MANIFEST.write_text(json.dumps(manifest, indent=2))

    total_bytes = sum(m["bytes"] for m in manifest)
    print(json.dumps({**stats, "manifest_docs": len(manifest), "total_bytes": total_bytes,
                      "campaigns_with_docs": len({m["campaign_number"] for m in manifest}),
                      "seconds": round(time.perf_counter() - started, 1)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
