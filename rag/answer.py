"""Grounded answer generation + hallucination guards.

Guards (in order):
 1. Abstain gate   : if the best reranker score is below a threshold, don't even call the LLM.
 2. Grounded prompt: numbered sources, cite-or-abstain rules, region/chapter separation, text-layer beats vision.
 3. Verification   : every number in the answer must occur in the sources it cites (or the question) -> flagged otherwise.
"""
from __future__ import annotations
import re, time
from dataclasses import dataclass, field
from . import llm
from .retrieve import Retriever, Result, Hit
from .common import DOCS

ABSTAIN = "I could not find this in the document."
MIN_SCORE = -3.0        # bge-reranker logit; calibrated on eval set (see eval report)

SYSTEM = """You are a careful document question-answering assistant.
Answer ONLY from the numbered SOURCES. Rules:
1. Cite every fact with its source tag, e.g. [S2]. Never cite a source that does not contain the fact.
2. Quote numbers, units, names and dates exactly as written in the sources. Do not compute, round or convert unless asked.
3. If the sources do not contain the answer, reply exactly: "I could not find this in the document." Do not guess.
4. Keep regions, chapters, products and years separate: only use facts from the section the question asks about.
5. Sources of kind "chart" are machine-read descriptions of images and can contain errors; if a "text", "table" or "callout" source gives the same figure, trust that one.
6. Never add figures that are not printed in the sources: no estimates, conversions, sums or percentages-of-totals (no "≈" values).
7. Be concise: 1-4 sentences unless the question asks for a list or summary. Mention the page number(s) in the answer."""

_NUM = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?%?")


_ODD_SPACES = dict.fromkeys(map(ord, "\u00a0\u2007\u2009\u200a\u202f"), " ")


def clean_text(txt: str) -> str:
    """Models like to emit narrow no-break spaces / non-breaking hyphens; normalise so downstream matching and UI are clean."""
    return txt.translate(_ODD_SPACES).replace("\u2011", "-")


def normalize_citations(txt: str) -> str:
    """Models emit [S2], \u3010S2\u3011, [S1\u2020L1-L3] or [S1, S2]; normalise all of them to [S1][S2] (every source kept)."""
    def fix(m):
        nums = list(dict.fromkeys(re.findall(r"\bS(\d+)", m.group(1))))
        return "".join(f"[S{n}]" for n in nums) if nums else m.group(0)
    txt = re.sub(r"[\[\u3010]([^\]\u3011]*?\bS\d+[^\]\u3011]*)[\]\u3011]", fix, txt)
    return re.sub(r"(\[S\d+\])(?:\s*\1)+", lambda m: m.group(1), txt)


def _numbers(s: str) -> set[str]:
    out = set()
    for m in _NUM.findall(s):
        out.add(m.replace("$", "").replace(",", "").rstrip("%").rstrip("."))
    return out


@dataclass
class Answer:
    question: str
    answer: str
    hits: list[Hit]
    analysis: dict
    cited: list[int] = field(default_factory=list)
    ungrounded_numbers: list[str] = field(default_factory=list)
    abstained: bool = False
    timings: dict = field(default_factory=dict)
    model: str = ""

    def sources(self):
        return [{"tag": f"S{i+1}", "doc": h.chunk.doc, "page": h.chunk.page, "page_end": h.chunk.page_end,
                 "section": " > ".join(h.chunk.section_path), "kind": h.chunk.kind,
                 "score": round(h.score, 2), "why": h.why, "text": h.text_for_llm()}
                for i, h in enumerate(self.hits)]


def build_context(hits: list[Hit], max_words: int = 1300) -> str:
    parts, used = [], 0
    for i, h in enumerate(hits):
        c = h.chunk
        sec = " > ".join(c.section_path)
        head = f"[S{i+1}] document: {DOCS.get(c.doc, {}).get('title', c.doc)} | page {c.page}" + \
               (f"-{c.page_end}" if c.page_end != c.page else "") + (f" | section: {sec}" if sec else "") + f" | kind: {c.kind}"
        body = h.text_for_llm()
        w = len(body.split())
        if used + w > max_words and parts:
            break
        parts.append(f"{head}\n{body}")
        used += w
    return "\n\n".join(parts)


def answer(question: str, retriever: Retriever, doc: str | None = None, k: int = 6, model: str | None = None,
           min_score: float = MIN_SCORE, verify: bool = True, max_wait: float | None = None) -> Answer:
    t0 = time.time()
    res: Result = retriever.search(question, doc=doc, k=k)
    t1 = time.time()
    if not res.hits or (retriever.mode != "naive" and res.hits[0].score < min_score):
        return Answer(question, ABSTAIN, res.hits, res.analysis, abstained=True,
                      timings={**res.timings, "llm": 0.0, "total": time.time() - t0})
    ctx = build_context(res.hits)
    msg = [{"role": "system", "content": SYSTEM},
           {"role": "user", "content": f"SOURCES:\n{ctx}\n\nQUESTION: {question}\n\nANSWER (with [S#] citations):"}]
    txt = normalize_citations(clean_text(llm.chat(msg, model=model, max_tokens=700, reasoning_effort="low", max_wait=max_wait)))
    used = llm.LAST_MODEL
    t2 = time.time()
    cited = sorted({int(x) for x in re.findall(r"\[S(\d+)\]", txt) if 0 < int(x) <= len(res.hits)})
    abst = txt.strip().startswith(ABSTAIN[:25])
    bad: list[str] = []
    if verify and not abst:
        src_text = " ".join(res.hits[i - 1].text_for_llm() for i in (cited or range(1, len(res.hits) + 1)))
        allowed = _numbers(src_text) | _numbers(question)
        # page references and list numbers are not claims about the document
        pages = {str(res.hits[i - 1].chunk.page) for i in range(1, len(res.hits) + 1)}
        body = re.sub(r"\[S\d+\]", "", txt)
        body = re.sub(r"\b(?:pages?|pp?\.)\s*[\d–\-, and]+", "", body, flags=re.I)
        for n in _numbers(body):
            if n not in allowed and n not in pages and not (len(n) <= 1):
                bad.append(n)
    return Answer(question, txt, res.hits, res.analysis, cited, bad, abst,
                  {**res.timings, "llm": t2 - t1, "total": t2 - t0}, used)
