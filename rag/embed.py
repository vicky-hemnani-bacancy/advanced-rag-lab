"""Local embedding model + cross-encoder reranker (ONNX via fastembed; no API cost, no GPU needed)."""
from __future__ import annotations
import os
import numpy as np

EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-base-en-v1.5")
RERANK_MODEL = os.getenv("RERANK_MODEL", "jinaai/jina-reranker-v1-turbo-en")
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_emb = None
_rr = None


def _embedder():
    global _emb
    if _emb is None:
        from fastembed import TextEmbedding
        _emb = TextEmbedding(EMBED_MODEL, threads=os.cpu_count())
    return _emb


def _reranker():
    global _rr
    if _rr is None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        _rr = TextCrossEncoder(RERANK_MODEL, threads=os.cpu_count())
    return _rr


def _norm(a: np.ndarray) -> np.ndarray:
    return a / np.clip(np.linalg.norm(a, axis=1, keepdims=True), 1e-9, None)


def embed_docs(texts: list[str], batch_size: int = 32) -> np.ndarray:
    vecs = list(_embedder().embed(texts, batch_size=batch_size))
    return _norm(np.array(vecs, dtype="float32"))


def embed_query(q: str) -> np.ndarray:
    return _norm(np.array(list(_embedder().embed([QUERY_PREFIX + q])), dtype="float32"))[0]


def rerank(query: str, texts: list[str]) -> list[float]:
    if not texts:
        return []
    return [float(s) for s in _reranker().rerank(query, texts)]
