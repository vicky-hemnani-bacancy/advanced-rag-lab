"""Shared types and helpers for the RAG pipelines."""
from __future__ import annotations
import re, json, hashlib
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "store"
CACHE = ROOT / "cache"
PDF_DIR = Path(r"C:\Users\Bacancy\Downloads")

DOCS = {
    "gpo": {"file": "GPO-Anual-report.pdf", "title": "GPO 2018 Annual Report",
            "desc": "U.S. Government Publishing Office FY2018 annual report: narrative text about GPO programs, govinfo, FDLP depository libraries, printing procurement, finances."},
    "gep": {"file": "GEP-Jun-2026.pdf", "title": "World Bank Global Economic Prospects, June 2026",
            "desc": "World Bank 200-page report: global outlook, regional outlooks (East Asia, South Asia, Sub-Saharan Africa...), sovereign debt in EMDEs, fiscal policy and commodity prices."},
    "imac": {"file": "iMac_PER_Oct2024.pdf", "title": "Apple iMac Product Environmental Report (Oct 2024)",
             "desc": "Apple iMac environmental report: carbon footprint, recycled materials, energy use, packaging, power consumption table, footnotes."},
}


@dataclass
class Chunk:
    id: str
    doc: str
    text: str                      # clean text shown to the LLM / user
    page: int                      # first page (1-based)
    page_end: int
    section_path: list[str] = field(default_factory=list)
    kind: str = "text"             # text | table | chart | footnote | callout
    parent_id: str | None = None
    meta: dict = field(default_factory=dict)

    @property
    def embed_text(self) -> str:
        """Contextual header + text: this is what gets embedded and BM25-indexed."""
        sec = " > ".join(self.section_path)
        head = f"[{DOCS.get(self.doc, {}).get('title', self.doc)}"
        head += f" | {sec}" if sec else ""
        head += f" | page {self.page}" + (f" | {self.kind}" if self.kind != "text" else "") + "]"
        return f"{head}\n{self.text}"

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        return Chunk(**d)


def make_id(doc: str, *parts) -> str:
    return doc + "-" + hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:10]


def n_words(s: str) -> int:
    return len(s.split())


_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\u201c\"(])")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.split(text) if s.strip()]


def pack_paragraphs(paras: list[str], target: int = 220, hard_max: int = 320, overlap_sents: int = 1) -> list[str]:
    """Pack paragraphs into ~target-word chunks on sentence boundaries, with sentence overlap."""
    sents: list[str] = []
    for p in paras:
        sents.extend(split_sentences(p) or [p])
    chunks, cur, cur_w = [], [], 0
    for s in sents:
        w = n_words(s)
        if cur and (cur_w + w > hard_max or cur_w >= target):
            chunks.append(" ".join(cur))
            cur = cur[-overlap_sents:] if overlap_sents else []
            cur_w = sum(n_words(x) for x in cur)
        cur.append(s)
        cur_w += w
    if cur and (not chunks or " ".join(cur) != chunks[-1]):
        chunks.append(" ".join(cur))
    return chunks


def save_chunks(name: str, chunks: list[Chunk]):
    STORE.mkdir(exist_ok=True)
    with open(STORE / f"{name}.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")


def load_chunks(name: str) -> list[Chunk]:
    p = STORE / f"{name}.jsonl"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return [Chunk.from_dict(json.loads(l)) for l in f]
