"""Demo data bundle (ADR-0091): the redacted database, the local vector index and the small models, packed
as one tar.gz so a hosted copy of the app can run the full pipeline without re-ingesting NHTSA data or
re-embedding the corpus.

  build(out)          pack the files in BUNDLE_PATHS (the database copy has complaint narratives redacted)
  ensure(url, sha256) download, verify and unpack into the repo root when data/vsia.db is missing
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

from vsia import config
from vsia.guardrails import redact

DB_NAME = "vsia.db"
# Relative to the repo root. Index namespaces and models the triage agent and RAG chat load at run time.
BUNDLE_PATHS = ["data/index/recalls", "data/index/recall_docs", "data/index/complaints",
                "data/models/component_clf.joblib", "data/models/component_clf_metrics.json"]
BUNDLE_GLOBS = ["data/models/routing_*.json", "data/models/confidence_calibrator_*.joblib"]
MARKER = "data/.bundle.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _redacted_db_copy(src: Path, dst: Path) -> int:
    """Copy the SQLite database and redact every complaint narrative in the copy. Returns rows changed."""
    shutil.copyfile(src, dst)
    con = sqlite3.connect(dst)
    try:
        changed = 0
        rows = con.execute("select odi_number, summary from complaints").fetchall()
        for odi, summary in rows:
            red = redact(summary or "").text
            if red != summary:
                con.execute("update complaints set summary = ? where odi_number = ?", (red, odi))
                changed += 1
        con.commit()
        con.execute("vacuum")
    finally:
        con.close()
    return changed


def build(out: Path, root: Path = config.REPO_ROOT) -> dict:
    """Write the bundle to `out` and return its manifest (also stored inside the archive)."""
    files = [root / p for p in BUNDLE_PATHS]
    files += sorted(f for g in BUNDLE_GLOBS for f in root.glob(g))
    missing = [str(f.relative_to(root)) for f in files if not f.exists()]
    if missing:
        raise FileNotFoundError(f"bundle inputs missing: {missing}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / DB_NAME
        redacted = _redacted_db_copy(root / "data" / DB_NAME, db_copy)
        manifest = {"built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "complaints_redacted": redacted,
                    "files": [f"data/{DB_NAME}"] + [str(f.relative_to(root)) for f in files]}
        man_path = Path(tmp) / "bundle_manifest.json"
        man_path.write_text(json.dumps(manifest, indent=2))
        with tarfile.open(out, "w:gz") as tar:
            tar.add(db_copy, arcname=f"data/{DB_NAME}")
            for f in files:
                tar.add(f, arcname=str(f.relative_to(root)))
            tar.add(man_path, arcname="data/bundle_manifest.json")
    manifest["sha256"] = sha256_file(out)
    manifest["bytes"] = out.stat().st_size
    return manifest


def _safe_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    """Only regular files and directories under data/, no absolute paths or parent references."""
    ok = []
    for m in tar.getmembers():
        p = Path(m.name)
        if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] != "data":
            raise ValueError(f"unsafe path in bundle: {m.name}")
        if not (m.isfile() or m.isdir()):
            raise ValueError(f"unsupported member type in bundle: {m.name}")
        ok.append(m)
    return ok


def installed(root: Path = config.REPO_ROOT) -> bool:
    return (root / "data" / DB_NAME).exists() and (root / MARKER).exists()


def ensure(url: str, sha256: str | None = None, root: Path = config.REPO_ROOT) -> dict:
    """Download and unpack the bundle unless it is already installed. Verifies sha256 when given."""
    if installed(root):
        return json.loads((root / MARKER).read_text())
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bundle.tar.gz"
        with httpx.stream("GET", url, follow_redirects=True, timeout=300.0) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
        digest = sha256_file(path)
        if sha256 and digest != sha256.lower():
            raise ValueError(f"bundle checksum mismatch: expected {sha256}, got {digest}")
        with tarfile.open(path, "r:gz") as tar:
            tar.extractall(root, members=_safe_members(tar))
    info = {"url": url, "sha256": digest, "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (root / MARKER).write_text(json.dumps(info, indent=2))
    return info
