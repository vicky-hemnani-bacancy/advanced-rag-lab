"""Vector store (ChromaDB, persistent) + BM25 keyword index over the same chunks."""
from __future__ import annotations
import re
import chromadb
from rank_bm25 import BM25Okapi
from .common import Chunk, STORE, save_chunks, load_chunks
from . import embed

_client = None


def client():
    global _client
    if _client is None:
        STORE.mkdir(exist_ok=True)
        _client = chromadb.PersistentClient(path=str(STORE / "chroma"))
    return _client


_TOK = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")
_STOP = {"the", "a", "an", "of", "in", "on", "to", "and", "or", "is", "are", "was", "were", "for", "by", "with", "at",
         "as", "that", "this", "it", "its", "be", "from", "what", "how", "does", "do", "did", "which", "who", "than"}


def tokenize(text: str) -> list[str]:
    toks = [t for t in _TOK.findall(text.lower()) if t not in _STOP]
    return [t[:-1] if len(t) > 3 and t.endswith("s") and not t[-2] == "s" else t for t in toks]


def _meta(c: Chunk) -> dict:
    m = {"doc": c.doc, "page": c.page, "kind": c.kind, "section": " > ".join(c.section_path)}
    for k, v in c.meta.items():
        if isinstance(v, (str, int, float, bool)):
            m[k] = v
    return m


def build_index(name: str, chunks: list[Chunk], batch: int = 64, progress=None):
    """Embed + persist chunks. Re-running replaces the collection."""
    seen: dict[str, int] = {}
    for c in chunks:                                   # ids must be unique inside a collection
        n = seen.get(c.id, 0)
        seen[c.id] = n + 1
        if n:
            c.id = f"{c.id}-{n}"
    save_chunks(name, chunks)
    cl = client()
    try:
        cl.delete_collection(name)
    except Exception:
        pass
    col = cl.create_collection(name, metadata={"hnsw:space": "cosine"})
    for i in range(0, len(chunks), batch):
        part = chunks[i:i + batch]
        vecs = embed.embed_docs([c.embed_text for c in part])
        col.add(ids=[c.id for c in part], embeddings=vecs.tolist(),
                documents=[c.text for c in part], metadatas=[_meta(c) for c in part])
        if progress:
            progress(min(i + batch, len(chunks)), len(chunks))


class Index:
    def __init__(self, name: str):
        self.name = name
        self.chunks = load_chunks(name)
        self.by_id = {c.id: c for c in self.chunks}
        self.col = client().get_collection(name)
        self._bm25 = BM25Okapi([tokenize(c.embed_text) for c in self.chunks]) if self.chunks else None
        self._pos = {c.id: i for i, c in enumerate(self.chunks)}

    def dense(self, qvec, k: int = 40, where: dict | None = None) -> list[tuple[str, float]]:
        r = self.col.query(query_embeddings=[qvec.tolist()], n_results=min(k, max(1, len(self.chunks))), where=where)
        return [(i, 1.0 - d) for i, d in zip(r["ids"][0], r["distances"][0])]

    def bm25(self, query: str, k: int = 40, allowed: set[str] | None = None) -> list[tuple[str, float]]:
        scores = self._bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: -scores[i])
        out = []
        for i in order:
            c = self.chunks[i]
            if allowed is not None and c.id not in allowed:
                continue
            if scores[i] <= 0:
                break
            out.append((c.id, float(scores[i])))
            if len(out) >= k:
                break
        return out

    def neighbours(self, cid: str, n: int = 1) -> list[Chunk]:
        """Adjacent chunks in document order that share the same section (for context expansion)."""
        i = self._pos[cid]
        base = self.chunks[i]
        out = []
        for j in range(max(0, i - n), min(len(self.chunks), i + n + 1)):
            if j != i and self.chunks[j].section_path == base.section_path and self.chunks[j].kind == "text" and base.kind == "text":
                out.append(self.chunks[j])
        return out
