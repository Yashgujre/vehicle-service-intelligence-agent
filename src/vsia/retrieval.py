"""Vector index and retrieval (FR-3).

Two interchangeable stores behind one protocol:

  LocalStore     Ollama nomic-embed-text vectors (768-d) in numpy files plus BM25 over the same chunks,
                 fused with reciprocal rank fusion (RRF). Runs with zero keys.
  PineconeStore  Pinecone integrated-embedding index (llama-text-embed-v2, 1024-d), SDK v10 keyword-only
                 data-plane calls. Dense only. Separate index: vectors from the two models are not comparable.

Records are flat dicts: {"id": str, "text": str, <metadata fields>}. Filters are a simple dict
{field: value | [values]}; a record matches when, for every field, its value (or any element of its list
value) equals the value (or one of the values). PineconeStore translates the same dict into $eq/$in/$and.

Namespaces (config retrieval.namespaces): recalls, recall_docs, tsbs, complaints.

Public helpers for other workstreams:
  search_recalls_for_complaint(make, model, model_year, text, top_k=5)  -> campaign-level hits (triage agent)
  search_complaints(text, filter=None, top_k=5)                          -> complaint hits (RAG chat)
  search_sources(text, namespaces=None, filter=None, top_k=5)            -> cross-namespace hits (RAG chat)
  model_family(model), vehicle_key(make, model, model_year)              -> model-string normalisation
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from vsia import config
from vsia.guardrails import redact
from vsia.schemas import RetrievalHit

INDEX_DIR = config.DATA_DIR / "index"
EMBED_BATCH = 64
PINECONE_BATCH = 96
PINECONE_TEXT_FIELD = "chunk_text"
PINECONE_EMBED_MODEL = "llama-text-embed-v2"

# nomic-embed-text is trained with task prefixes; documents and queries use different ones.
DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

# Fields returned by Pinecone search per namespace (Pinecone returns only what is requested).
NAMESPACE_FIELDS: dict[str, list[str]] = {
    "recalls": ["campaign_number", "make", "model", "model_year", "model_family", "component",
                "component_raw", "report_date", "doc_type", "source_url"],
    "recall_docs": ["campaign_number", "make", "models", "model_years", "component", "doc_type",
                    "source_url", "page", "chunk_index"],
    "tsbs": ["tsb_id", "make", "models", "model_years", "component", "communication_type", "date"],
    "complaints": ["odi_number", "make", "model", "model_year", "model_family", "date_filed", "crash", "fire"],
}


# --------------------------------------------------------------------------------------------------
# Model-string normalisation
# --------------------------------------------------------------------------------------------------

_PAREN_RE = re.compile(r"\([^)]*\)")
_SEAT_RE = re.compile(r"\b\d\s*-?\s*SEAT(ER)?\b")
_VARIANTS_RE = re.compile(r"\bALL VARIANTS\b")
_PLUGIN_RE = re.compile(r"\bPLUG\s*-?\s*IN\b")
# Powertrain badges NHTSA appends inconsistently ('F-150 LIGHTNING BEV' vs 'F-150 LIGHTNING',
# 'RAV4 PRIME' renamed 'RAV4 PLUG-IN HYBRID'). 'EV' is kept: 'EQUINOX EV' and 'EQUINOX' are different
# vehicles.
_POWERTRAIN_TOKENS = {"BEV", "HEV", "PHEV", "HYBRID", "PLUGIN", "PRIME", "ELECTRIC"}


def model_family(model: str | None) -> str:
    """Normalised model family key that tolerates NHTSA model-string drift.

    'MUSTANG MACH-E' / 'MUSTANG MACH E' / 'MUSTANG MACH-E BEV' -> 'MUSTANGMACHE'
    'F-150 (SUPER CREW) LIGHTNING BEV' / 'F-150 LIGHTNING'     -> 'F150LIGHTNING'
    'MODEL Y (All Variants)' / 'MODEL Y  5-SEAT'              -> 'MODELY'
    'RAV4 PRIME' / 'RAV4 PLUG-IN HYBRID' / 'RAV4 HYBRID'      -> 'RAV4'
    'ID.4' -> 'ID4'; 'IONIQ 5 N' -> 'IONIQ5N' (performance model kept distinct); 'EQUINOX EV' -> 'EQUINOXEV'
    """
    if not model:
        return ""
    s = model.upper()
    s = _PAREN_RE.sub(" ", s)
    s = _SEAT_RE.sub(" ", s)
    s = _VARIANTS_RE.sub(" ", s)
    s = _PLUGIN_RE.sub(" PLUGIN ", s)
    tokens = [t for t in re.split(r"[^A-Z0-9]+", s) if t and t not in _POWERTRAIN_TOKENS]
    return "".join(tokens)


def vehicle_key(make: str | None, model: str | None, model_year: int | str | None) -> str:
    """'FORD|MUSTANGMACHE|2022'. Stored as a (list) metadata field so one exact-match filter works in both
    stores, including for documents that cover several vehicles."""
    return f"{(make or '').strip().upper()}|{model_family(model)}|{int(model_year) if model_year else ''}"


# --------------------------------------------------------------------------------------------------
# Embeddings
# --------------------------------------------------------------------------------------------------

Embedder = Callable[[list[str]], list[list[float]]]


def _ollama_embedder(texts: list[str]) -> list[list[float]]:
    from vsia.llm import embed_ollama

    return embed_ollama(texts)


@lru_cache
def _fastembed_model():
    from fastembed import TextEmbedding

    return TextEmbedding(config.settings()["embeddings"]["providers"]["fastembed"]["model"])


def _fastembed_embedder(texts: list[str]) -> list[list[float]]:
    return [v.tolist() for v in _fastembed_model().embed(texts)]


def _default_embedder() -> Embedder:
    """VSIA_EMBED_PROVIDER=fastembed runs the same model in-process (hosted demo, ADR-0090); default Ollama."""
    return _fastembed_embedder if (config.env().vsia_embed_provider or "").lower() == "fastembed" \
        else _ollama_embedder


_embedder: Embedder | None = None


def set_embedder(fn: Embedder | None) -> None:
    """Swap the embedding function (tests use a deterministic fake). None restores the configured default."""
    global _embedder
    _embedder = fn


def embed_texts(texts: Sequence[str], prefix: str = "", batch_size: int = EMBED_BATCH,
                progress: Callable[[int, int], None] | None = None) -> np.ndarray:
    """L2-normalised float32 matrix, one row per text."""
    out: list[list[float]] = []
    embed = _embedder or _default_embedder()
    for i in range(0, len(texts), batch_size):
        out.extend(embed([prefix + t for t in texts[i:i + batch_size]]))
        if progress:
            progress(min(i + batch_size, len(texts)), len(texts))
    if not out:
        return np.zeros((0, 0), dtype=np.float32)
    m = np.asarray(out, dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


# --------------------------------------------------------------------------------------------------
# BM25, filters, fusion
# --------------------------------------------------------------------------------------------------

_STOP = set("""a an and are as at be been but by for from had has have he her his i if in into is it its
me my not of on or our she so that the their them then there they this to was we were what when which who
will with you your""".split())


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOP]


def _norm_value(v: Any) -> str:
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip().upper()


def matches_filter(meta: dict, flt: dict | None) -> bool:
    """Exact match with list semantics on both sides; int and str forms of a value compare equal."""
    if not flt:
        return True
    for field, want in flt.items():
        if want is None:
            continue
        have = meta.get(field)
        if have is None:
            return False
        haves = have if isinstance(have, (list, tuple, set)) else [have]
        wants = want if isinstance(want, (list, tuple, set)) else [want]
        if not {_norm_value(h) for h in haves} & {_norm_value(w) for w in wants}:
            return False
    return True


def rrf_fuse(rankings: Sequence[Sequence[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal rank fusion: score(d) = sum over rankings of 1 / (k + rank), rank starting at 1."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


# --------------------------------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------------------------------

_PAGE_RE = re.compile(r"<!--\s*page\s+(\d+)\s*-->")


def approx_tokens(text: str) -> int:
    """Rough token count (about 0.75 words per token for English prose)."""
    return math.ceil(len(text.split()) * 4 / 3)


def chunk_markdown(markdown: str, max_tokens: int = 800, overlap_tokens: int = 100) -> list[dict]:
    """Paragraph-aware chunks of about max_tokens with about overlap_tokens carried over.

    Returns [{"text", "page", "chunk_index"}]; page is the page marker (<!-- page N -->) in effect at the
    start of the chunk, or None if the markdown has no markers."""
    max_words = max(1, int(max_tokens * 3 / 4))
    overlap_words = max(0, int(overlap_tokens * 3 / 4))
    # Units: (page, words) per paragraph, with oversized paragraphs split into max_words pieces.
    units: list[tuple[int | None, list[str]]] = []
    page: int | None = None
    for para in re.split(r"\n\s*\n", markdown):
        m = _PAGE_RE.search(para)
        if m:
            page = int(m.group(1))
            para = _PAGE_RE.sub("", para)
        words = para.split()
        for i in range(0, len(words), max_words):
            units.append((page, words[i:i + max_words]))

    chunks: list[dict] = []
    cur: list[str] = []
    cur_page: int | None = None
    carried = 0  # words in cur that came from the previous chunk's overlap

    def flush():
        nonlocal cur, carried
        if len(cur) > carried:
            chunks.append({"text": " ".join(cur), "page": cur_page, "chunk_index": len(chunks)})
            tail = cur[-overlap_words:] if overlap_words else []
            cur, carried = list(tail), len(tail)

    for upage, words in units:
        if not words:
            continue
        if len(cur) + len(words) > max_words and len(cur) > carried:
            flush()
        if len(cur) == carried:
            cur_page = upage
        cur.extend(words)
    flush()
    return chunks


# --------------------------------------------------------------------------------------------------
# Store protocol and implementations
# --------------------------------------------------------------------------------------------------


class VectorStore(Protocol):
    name: str

    def upsert(self, namespace: str, records: list[dict]) -> int: ...

    def search(self, namespace: str, query: str, top_k: int = 5,
               filter: dict | None = None) -> list[RetrievalHit]: ...


def _split_record(rec: dict) -> tuple[str, str, dict]:
    meta = {k: v for k, v in rec.items() if k not in ("id", "_id", "text") and v is not None}
    return str(rec.get("id") or rec["_id"]), rec["text"], meta


class _LocalNamespace:
    def __init__(self, ids: list[str], texts: list[str], metas: list[dict], vectors: np.ndarray):
        from rank_bm25 import BM25Okapi

        self.ids, self.texts, self.metas, self.vectors = ids, texts, metas, vectors
        self.bm25 = BM25Okapi([tokenize(t) or ["_"] for t in texts]) if texts else None


class LocalStore:
    """Numpy + jsonl per namespace under data/index/<namespace>/; cosine similarity plus BM25 with RRF."""

    name = "local"

    def __init__(self, root: Path | str = INDEX_DIR, hybrid: bool | None = None, rrf_k: int | None = None):
        rcfg = config.settings().get("retrieval", {})
        self.root = Path(root)
        self.hybrid = rcfg.get("hybrid", True) if hybrid is None else hybrid
        self.rrf_k = rcfg.get("rrf_k", 60) if rrf_k is None else rrf_k
        self._cache: dict[str, _LocalNamespace] = {}

    # ---- storage
    def _dir(self, namespace: str) -> Path:
        return self.root / namespace

    def reset(self, namespace: str) -> None:
        d = self._dir(namespace)
        for f in ("vectors.npy", "meta.jsonl", "info.json"):
            (d / f).unlink(missing_ok=True)
        self._cache.pop(namespace, None)

    def _load(self, namespace: str) -> _LocalNamespace:
        if namespace in self._cache:
            return self._cache[namespace]
        d = self._dir(namespace)
        ids: list[str] = []
        texts: list[str] = []
        metas: list[dict] = []
        vectors = np.zeros((0, 0), dtype=np.float32)
        if (d / "meta.jsonl").exists():
            with open(d / "meta.jsonl") as f:
                for line in f:
                    row = json.loads(line)
                    ids.append(row["id"])
                    texts.append(row["text"])
                    metas.append(row["metadata"])
            vectors = np.load(d / "vectors.npy")
        ns = _LocalNamespace(ids, texts, metas, vectors)
        self._cache[namespace] = ns
        return ns

    def count(self, namespace: str) -> int:
        return len(self._load(namespace).ids)

    def upsert(self, namespace: str, records: list[dict],
               progress: Callable[[int, int], None] | None = None) -> int:
        """Embed and add records; an existing id is replaced."""
        if not records:
            return 0
        new_ids, new_texts, new_metas = zip(*(_split_record(r) for r in records))
        new_vecs = embed_texts(list(new_texts), prefix=DOC_PREFIX, progress=progress)
        old = self._load(namespace)
        replace = set(new_ids)
        keep = [i for i, x in enumerate(old.ids) if x not in replace]
        ids = [old.ids[i] for i in keep] + list(new_ids)
        texts = [old.texts[i] for i in keep] + list(new_texts)
        metas = [old.metas[i] for i in keep] + list(new_metas)
        vecs = np.vstack([old.vectors[keep], new_vecs]) if keep else new_vecs
        d = self._dir(namespace)
        d.mkdir(parents=True, exist_ok=True)
        np.save(d / "vectors.npy", vecs.astype(np.float32))
        with open(d / "meta.jsonl", "w") as f:
            for i, t, m in zip(ids, texts, metas):
                f.write(json.dumps({"id": i, "text": t, "metadata": m}, default=str) + "\n")
        (d / "info.json").write_text(json.dumps({
            "namespace": namespace, "count": len(ids), "dim": int(vecs.shape[1]),
            "embedding_model": config.settings()["embeddings"]["providers"]["ollama"]["model"],
            "doc_prefix": DOC_PREFIX, "updated_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2))
        self._cache.pop(namespace, None)
        return len(new_ids)

    # ---- search
    def search(self, namespace: str, query: str, top_k: int = 5,
               filter: dict | None = None) -> list[RetrievalHit]:
        ns = self._load(namespace)
        if not ns.ids:
            return []
        allowed = np.array([matches_filter(m, filter) for m in ns.metas], dtype=bool) if filter \
            else np.ones(len(ns.ids), dtype=bool)
        if not allowed.any():
            return []
        candidates = max(top_k * 10, 50)

        q = embed_texts([query], prefix=QUERY_PREFIX)[0]
        dense = ns.vectors @ q
        dense_masked = np.where(allowed, dense, -np.inf)
        n_allowed = int(allowed.sum())
        dense_order = np.argsort(-dense_masked)[:min(candidates, n_allowed)]

        bm25_scores = None
        if self.hybrid and ns.bm25 is not None:
            q_tokens = tokenize(query)
            if q_tokens:
                bm25_scores = ns.bm25.get_scores(q_tokens)
                bm = np.where(allowed & (bm25_scores > 0), bm25_scores, -np.inf)
                n_pos = int(np.isfinite(bm).sum())
                bm_order = np.argsort(-bm)[:min(candidates, n_pos)]
            else:
                bm_order = np.array([], dtype=int)

        if bm25_scores is None:
            picked = [(int(i), float(dense[i])) for i in dense_order[:top_k]]
        else:
            fused = rrf_fuse([[str(i) for i in dense_order], [str(i) for i in bm_order]], k=self.rrf_k)
            picked = [(int(i), s) for i, s in fused[:top_k]]

        hits = []
        for idx, score in picked:
            meta = dict(ns.metas[idx])
            meta["retrieval"] = {
                "store": self.name,
                "fusion": "rrf" if bm25_scores is not None else "dense",
                "dense_cosine": round(float(dense[idx]), 6),
                "bm25": round(float(bm25_scores[idx]), 6) if bm25_scores is not None else None,
            }
            hits.append(RetrievalHit(id=ns.ids[idx], namespace=namespace, score=round(score, 6),
                                     text=ns.texts[idx], metadata=meta))
        return hits


# ---- Pinecone


def to_pinecone_record(rec: dict) -> dict:
    """Flat Pinecone text record: _id, chunk_text, metadata. Pinecone metadata allows strings, numbers,
    booleans and lists of strings only (no nulls, no nested objects), so lists are stringified and
    nested values dropped."""
    rid, text, meta = _split_record(rec)
    out: dict[str, Any] = {"_id": rid, PINECONE_TEXT_FIELD: text}
    for k, v in meta.items():
        if isinstance(v, (list, tuple, set)):
            out[k] = [str(x) for x in v]
        elif isinstance(v, (str, bool, int, float)):
            out[k] = v
        elif isinstance(v, dict):
            continue
        else:
            out[k] = str(v)
    return out


def build_pinecone_filter(flt: dict | None) -> dict | None:
    """{field: v} -> {field: {"$eq": v}}; {field: [a, b]} -> {field: {"$in": [a, b]}}; several fields are
    combined with $and (operators cannot sit at the top level)."""
    if not flt:
        return None
    clauses = []
    for field, want in flt.items():
        if want is None:
            continue
        if isinstance(want, (list, tuple, set)):
            clauses.append({field: {"$in": list(want)}})
        else:
            clauses.append({field: {"$eq": want}})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def build_pinecone_query(query: str, top_k: int, flt: dict | None) -> dict:
    q: dict[str, Any] = {"inputs": {"text": query}, "top_k": top_k}
    pf = build_pinecone_filter(flt)
    if pf:
        q["filter"] = pf
    return q


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return obj[key]
    except (KeyError, TypeError, IndexError):
        return getattr(obj, key.lstrip("_"), getattr(obj, key, default))


class PineconeStore:
    """Pinecone integrated-embedding index (llama-text-embed-v2). Requires PINECONE_API_KEY."""

    name = "pinecone"

    def __init__(self, index_name: str | None = None, api_key: str | None = None,
                 cloud: str = "aws", region: str = "us-east-1", create: bool = True):
        from pinecone import Pinecone

        key = api_key or config.env().pinecone_api_key
        if not key:
            raise RuntimeError("PINECONE_API_KEY is not set; use VSIA_VECTOR_STORE=local")
        self.index_name = index_name or config.env().pinecone_index
        self.pc = Pinecone(api_key=key)
        if create and not self.pc.has_index(self.index_name):
            self.pc.create_index_for_model(
                name=self.index_name, cloud=cloud, region=region,
                embed={"model": PINECONE_EMBED_MODEL, "field_map": {"text": PINECONE_TEXT_FIELD}},
            )
        self.index = self.pc.Index(host=self.pc.describe_index(self.index_name).host)

    def upsert(self, namespace: str, records: list[dict],
               progress: Callable[[int, int], None] | None = None) -> int:
        recs = [to_pinecone_record(r) for r in records]
        for i in range(0, len(recs), PINECONE_BATCH):
            self.index.upsert_records(namespace=namespace, records=recs[i:i + PINECONE_BATCH])
            if progress:
                progress(min(i + PINECONE_BATCH, len(recs)), len(recs))
        return len(recs)

    def search(self, namespace: str, query: str, top_k: int = 5,
               filter: dict | None = None) -> list[RetrievalHit]:
        fields = [PINECONE_TEXT_FIELD] + NAMESPACE_FIELDS.get(namespace, [])
        res = self.index.search(namespace=namespace, query=build_pinecone_query(query, top_k, filter),
                                fields=fields)
        hits = []
        for h in _get(_get(res, "result", {}), "hits", []) or []:
            fields_out = dict(_get(h, "fields", {}) or {})
            text = fields_out.pop(PINECONE_TEXT_FIELD, "")
            fields_out["retrieval"] = {"store": self.name, "fusion": "dense"}
            hits.append(RetrievalHit(id=str(_get(h, "_id")), namespace=namespace,
                                     score=float(_get(h, "_score", 0.0)), text=text, metadata=fields_out))
        return hits


@lru_cache
def get_store(kind: str | None = None) -> VectorStore:
    """Factory: env VSIA_VECTOR_STORE (local | pinecone), default local."""
    kind = (kind or config.env().vsia_vector_store or "local").lower()
    if kind == "pinecone":
        return PineconeStore()
    if kind == "local":
        return LocalStore()
    raise ValueError(f"unknown vector store: {kind}")


# --------------------------------------------------------------------------------------------------
# Task-level search functions
# --------------------------------------------------------------------------------------------------


def search(namespace: str, query: str, top_k: int | None = None, filter: dict | None = None,
           store: VectorStore | None = None) -> list[RetrievalHit]:
    top_k = top_k or config.settings().get("retrieval", {}).get("top_k", 5)
    return (store or get_store()).search(namespace, query, top_k=top_k, filter=filter)


def search_recalls_for_complaint(make: str, model: str, model_year: int, text: str, top_k: int = 5,
                                 store: VectorStore | None = None) -> list[RetrievalHit]:
    """Recall campaigns for one complaint's vehicle, ranked by similarity to the complaint text.

    Searches the recalls (API records) and recall_docs (parsed Part 573 and owner letters) namespaces with a
    vehicle filter on make + normalised model family + exact model year (vehicle_key), fuses the two
    rankings by RRF at campaign level, and returns at most top_k hits, one per campaign. Each hit has
    id = campaign number, metadata.campaign_number, metadata.component, metadata.sources (record ids) and
    metadata.best_dense_cosine (max cosine across the campaign's matching records, a confidence signal).
    An empty list means no recall in the index covers this vehicle."""
    store = store or get_store()
    rk = config.settings().get("retrieval", {}).get("rrf_k", 60)
    query = redact(text).text
    flt = {"vehicle_keys": [vehicle_key(make, model, model_year)]}
    per_ns = max(top_k * 4, 20)
    rankings: list[list[str]] = []
    best: dict[str, RetrievalHit] = {}
    sources: dict[str, list[str]] = {}
    cosine: dict[str, float] = {}
    for ns in ("recalls", "recall_docs"):
        hits = store.search(ns, query, top_k=per_ns, filter=flt)
        ranking: list[str] = []
        for h in hits:
            camp = h.metadata.get("campaign_number")
            if not camp:
                continue
            sources.setdefault(camp, []).append(f"{ns}:{h.id}")
            c = (h.metadata.get("retrieval") or {}).get("dense_cosine")
            if c is not None:
                cosine[camp] = max(cosine.get(camp, -1.0), c)
            if camp in ranking:
                continue
            ranking.append(camp)
            # Prefer the API record as the representative text: it is short and states the remedy.
            if camp not in best or (best[camp].namespace != "recalls" and ns == "recalls"):
                best[camp] = h
        rankings.append(ranking)
    out = []
    for camp, score in rrf_fuse(rankings, k=rk)[:top_k]:
        rep = best[camp]
        meta = {k: v for k, v in rep.metadata.items() if k != "retrieval"}
        meta.update({"campaign_number": camp, "sources": sources.get(camp, []),
                     "best_dense_cosine": cosine.get(camp), "representative": f"{rep.namespace}:{rep.id}"})
        out.append(RetrievalHit(id=camp, namespace="recalls", score=round(score, 6), text=rep.text,
                                metadata=meta))
    return out


def search_complaints(text: str, filter: dict | None = None, top_k: int = 5,
                      store: VectorStore | None = None) -> list[RetrievalHit]:
    """Similar complaints for the RAG chat. Filter fields: make, model, model_year, model_family,
    vehicle_keys, odi_number, crash, fire. The complaint index never contains NHTSA component labels."""
    return (store or get_store()).search("complaints", redact(text).text, top_k=top_k, filter=filter)


def search_sources(text: str, namespaces: Iterable[str] | None = None, filter: dict | None = None,
                   top_k: int = 5, store: VectorStore | None = None) -> list[RetrievalHit]:
    """Cross-namespace search for the RAG chat; namespaces fused by RRF on rank (scores from different
    namespaces are not comparable). Default namespaces: recalls, recall_docs, tsbs."""
    store = store or get_store()
    rk = config.settings().get("retrieval", {}).get("rrf_k", 60)
    query = redact(text).text
    by_key: dict[str, RetrievalHit] = {}
    rankings = []
    for ns in namespaces or ("recalls", "recall_docs", "tsbs"):
        hits = store.search(ns, query, top_k=top_k * 2, filter=filter)
        rankings.append([f"{ns}:{h.id}" for h in hits])
        by_key.update({f"{ns}:{h.id}": h for h in hits})
    return [by_key[k].model_copy(update={"score": round(s, 6)}) for k, s in rrf_fuse(rankings, k=rk)[:top_k]]


def timed_search(fn: Callable[..., Any], *args, **kwargs) -> tuple[Any, float]:
    t0 = time.perf_counter()
    res = fn(*args, **kwargs)
    return res, (time.perf_counter() - t0) * 1000
