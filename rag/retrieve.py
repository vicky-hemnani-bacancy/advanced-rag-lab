"""Hybrid retrieval: dense + BM25 (+ metadata-constrained variants) -> RRF fusion -> cross-encoder rerank -> context expansion."""
from __future__ import annotations
import time, threading
from dataclasses import dataclass, field
from .common import Chunk
from .store import Index
from . import embed, router


@dataclass
class Hit:
    chunk: Chunk
    score: float                      # cross-encoder score (+ routing boosts); higher = more relevant
    rrf: float = 0.0
    why: str = ""
    extra_context: str = ""           # neighbouring chunks (small-to-big)

    def text_for_llm(self) -> str:
        return (self.extra_context + "\n" if self.extra_context else "") + self.chunk.text


@dataclass
class Result:
    hits: list[Hit]
    analysis: dict
    timings: dict = field(default_factory=dict)
    mode: str = "advanced"


def rrf(lists: list[tuple[list[tuple[str, float]], float]], k: int = 60) -> dict[str, float]:
    s: dict[str, float] = {}
    for ranked, w in lists:
        for r, (cid, _) in enumerate(ranked):
            s[cid] = s.get(cid, 0.0) + w / (k + r + 1)
    return s


def _meta_match(c: Chunk, key: str, val) -> bool:
    return c.kind == val if key == "kind" else c.meta.get(key) == val


class Retriever:
    def __init__(self, docs: list[str], mode: str = "advanced"):
        self.mode = mode
        self.idx: dict[str, Index] = {d: Index(f"naive_{d}" if mode == "naive" else d) for d in docs}

    # ---------------------------------------------------------------- stage 1: candidates for one document
    def _candidates(self, query: str, doc: str, qv, n_cand: int):
        idx = self.idx[doc]
        an = router.analyze(query, doc)
        lists = [(idx.dense(qv, 40), 1.0), (idx.bm25(query, 40), 1.0)]
        matched: set[str] = set()
        for where, _ in an["hard"]:                    # constraint-restricted variants get extra weight
            try:
                d = idx.dense(qv, 30, where=where)
            except Exception:
                d = []
            ids = {c.id for c in idx.chunks if all(_meta_match(c, kk, vv) for kk, vv in where.items())}
            lists += [(d, 1.5), (idx.bm25(query, 30, allowed=ids), 1.5)]
            matched |= ids
        fused = rrf(lists)
        cand = sorted(fused, key=lambda c: -fused[c])[:n_cand]
        return cand, fused, an, matched

    # ---------------------------------------------------------------- stage 2: boosts + expansion
    def _boost(self, doc: str, cid: str, ce_score: float, rrf_s: float, an: dict, matched: set[str]) -> Hit:
        ch = self.idx[doc].by_id[cid]
        soft, bonus, why = an["soft"], 0.0, []
        if cid in matched:
            bonus += 2.0; why.append("matches query constraint")
        if soft.get("chapter_no") and ch.meta.get("chapter_no") == soft["chapter_no"]:
            bonus += 0.7; why.append("topic->chapter hint")
        if soft.get("kinds") and ch.kind in soft["kinds"]:
            bonus += 0.8; why.append(f"{ch.kind} for numeric question")
        return Hit(ch, ce_score + bonus, rrf_s, ", ".join(why) or "hybrid+rerank")

    def _expand(self, hits: list[Hit]):
        """Small-to-big: attach neighbouring chunks of the best narrative hits so the LLM sees the surrounding argument."""
        for h in hits[:3]:
            c = h.chunk
            if c.kind != "text":
                continue
            idx = self.idx[c.doc]
            nb = idx.neighbours(c.id, 1)
            prev = [n for n in nb if idx._pos[n.id] < idx._pos[c.id]]
            nxt = [n for n in nb if idx._pos[n.id] > idx._pos[c.id]]
            h.extra_context = " ".join(n.text for n in prev)[-900:]
            if nxt:
                h.chunk = Chunk(**{**c.to_dict(), "text": c.text + " " + nxt[0].text[:700]})

    # ---------------------------------------------------------------- public
    _lock = threading.Lock()          # the embedder/reranker/Chroma handles are shared; serialise searches across threads

    def search(self, query: str, doc: str | None = None, k: int = 6, n_cand: int = 20, expand: bool = True) -> Result:
        with Retriever._lock:
            return self._search(query, doc, k, n_cand, expand)

    def _search(self, query: str, doc: str | None = None, k: int = 6, n_cand: int = 20, expand: bool = True) -> Result:
        t0 = time.time()
        qv = embed.embed_query(query)
        t_emb = time.time()
        docs = [doc] if doc else list(self.idx)

        if self.mode == "naive":                       # baseline: dense only, top-k, no rerank, no routing
            hits = sorted([Hit(self.idx[d].by_id[c], s, why="dense") for d in docs for c, s in self.idx[d].dense(qv, k)],
                          key=lambda h: -h.score)[:k]
            return Result(hits, {"explain": "naive: dense top-k"}, {"embed": t_emb - t0, "total": time.time() - t0}, "naive")

        per_doc, pool = {}, []
        n_each = n_cand if doc else max(6, n_cand // len(docs) + 2)     # auto mode: fewer per doc, rerank once
        for d in docs:
            cand, fused, an, matched = self._candidates(query, d, qv, n_each)
            per_doc[d] = (fused, an, matched)
            pool += [(d, c) for c in cand]
        t_ret = time.time()

        scores = embed.rerank(query, [self.idx[d].by_id[c].embed_text[:1800] for d, c in pool])
        t_rr = time.time()

        hits = [self._boost(d, c, s, per_doc[d][0][c], per_doc[d][1], per_doc[d][2]) for (d, c), s in zip(pool, scores)]
        hits.sort(key=lambda h: -h.score)
        hits = hits[:k]
        if expand:
            self._expand(hits)
        explain = per_doc[docs[0]][1]["explain"] if doc else "searched all documents; the reranker picks the best passages"
        analysis = {**per_doc[docs[0]][1], "explain": explain} if doc else {"explain": explain, "hard": [], "soft": {}}
        return Result(hits, analysis, {"embed": t_emb - t0, "retrieve": t_ret - t_emb, "rerank": t_rr - t_ret,
                                       "total": time.time() - t0}, "advanced")
