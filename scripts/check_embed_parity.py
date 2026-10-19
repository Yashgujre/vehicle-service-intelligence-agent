"""Check that the in-process ONNX embedder (fastembed) reproduces the Ollama nomic-embed-text vectors stored
in the local index, so the hosted demo can search the same index without an Ollama server (ADR-0090).

Usage: python scripts/check_embed_parity.py [--model nomic-ai/nomic-embed-text-v1.5] [--n 50]
"""

from __future__ import annotations

import argparse
import json
import time

import numpy as np

from vsia import retrieval


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="nomic-ai/nomic-embed-text-v1.5")
    ap.add_argument("--n", type=int, default=50)
    a = ap.parse_args()

    from fastembed import TextEmbedding

    t0 = time.perf_counter()
    emb = TextEmbedding(a.model)
    load_s = time.perf_counter() - t0
    out = {"model": a.model, "load_seconds": round(load_s, 1)}
    for ns in ("recalls", "recall_docs", "complaints"):
        d = retrieval.INDEX_DIR / ns
        rows = [json.loads(line) for _, line in zip(range(a.n), open(d / "meta.jsonl"))]
        stored = np.load(d / "vectors.npy")[: len(rows)]
        t0 = time.perf_counter()
        new = np.asarray(list(emb.embed([retrieval.DOC_PREFIX + r["text"] for r in rows])), dtype=np.float32)
        secs = time.perf_counter() - t0
        new /= np.linalg.norm(new, axis=1, keepdims=True)
        cos = (new * stored).sum(axis=1)
        top1 = float(np.mean(np.argmax(new @ stored.T, axis=1) == np.arange(len(rows))))
        out[ns] = {"n": len(rows), "cosine_min": round(float(cos.min()), 5),
                   "cosine_mean": round(float(cos.mean()), 5), "self_top1": top1,
                   "ms_per_text": round(secs * 1000 / len(rows), 1)}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
