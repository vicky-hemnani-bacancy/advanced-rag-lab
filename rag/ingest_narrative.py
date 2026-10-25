"""Use case 1 - GPO annual report: plain narrative text.

Parsing   : column-aware reading order, running headers/footers/captions dropped.
Chunking  : heading-aware sections, paragraphs packed on sentence boundaries (~220 words, 1 sentence overlap),
            every chunk keeps page numbers + section heading so it can be cited.
"""
from __future__ import annotations
import collections, re
import pymupdf
from .common import Chunk, make_id, n_words, split_sentences, PDF_DIR, DOCS
from . import layout


def pack_units(units: list[tuple[str, int]], target=220, hard_max=320, overlap=1):
    """units = [(text, page)]. Returns [(chunk_text, page_start, page_end)] split on sentence boundaries."""
    sents: list[tuple[str, int]] = []
    for text, page in units:
        for s in (split_sentences(text) or [text]):
            sents.append((s, page))
    out, cur, cur_w = [], [], 0
    for s, pg in sents:
        w = n_words(s)
        if cur and (cur_w + w > hard_max or cur_w >= target):
            out.append((" ".join(x[0] for x in cur), cur[0][1], cur[-1][1]))
            cur = cur[-overlap:] if overlap else []
            cur_w = sum(n_words(x[0]) for x in cur)
        cur.append((s, pg))
        cur_w += w
    if cur and (not out or " ".join(x[0] for x in cur) != out[-1][0]):
        out.append((" ".join(x[0] for x in cur), cur[0][1], cur[-1][1]))
    return out


def is_heading(b: layout.Block, body: float) -> int:
    """0 = not a heading, 1 = major heading, 2 = minor heading."""
    words = len(b.text.split())
    if words > 14 or b.text.rstrip().endswith((".", ",", ";")) and not b.text.isupper():
        return 0
    if b.size >= max(14, body * 1.35) and b.bold:
        return 1
    if b.bold and b.size >= max(11.5, body * 1.1) and words <= 9:
        return 2
    return 0


def ingest(doc_key: str = "gpo") -> list[Chunk]:
    pdf = pymupdf.open(PDF_DIR / DOCS[doc_key]["file"])
    headers = layout.running_headers(pdf)
    chunks: list[Chunk] = []
    section: list[str] = []
    units: list[tuple[str, int]] = []

    # pre-pass: a "heading" that repeats on many pages is a running title, not a section
    repeats = collections.Counter()
    for page in pdf:
        bl = layout.page_blocks(page)
        if not bl:
            continue
        sz = collections.Counter()
        for b in bl:
            sz[b.size] += len(b.text)
        for b in bl:
            if is_heading(b, sz.most_common(1)[0][0]):
                repeats[layout._norm(b.text)] += 1

    def flush():
        nonlocal units
        if not units:
            return
        for text, p0, p1 in pack_units(units):
            if n_words(text) < 12:
                continue
            chunks.append(Chunk(make_id(doc_key, len(chunks), text[:40]), doc_key, text, p0, p1, list(section)))
        units = []

    for page in pdf:
        blocks = layout.page_blocks(page)
        if not blocks:
            continue
        sizes = collections.Counter()
        for b in blocks:
            sizes[b.size] += len(b.text)
        body = sizes.most_common(1)[0][0]
        blocks = layout.clean_blocks(page, blocks, headers)
        for b in layout.reading_order(blocks, page.rect.width):
            H = page.rect.height
            if (b.y1 < H * 0.07 or b.y0 > H * 0.92) and b.size < body * 0.8:
                continue                                   # tiny running footer / header
            h = is_heading(b, body)
            if h and (page.number + 1 < 8 or repeats[layout._norm(b.text)] >= 4):
                continue                                   # cover pages / running titles are not sections
            if h:
                flush()
                section = (section[:h - 1] if h > 1 else []) + [b.text.strip()]
                section = section[:2]
                continue
            if b.size < body * 0.82 and n_words(b.text) < 25:
                continue                                   # captions / labels
            if re.fullmatch(r"[\W\d_]+", b.text):
                continue
            units.append((b.text, page.number + 1))
    flush()
    return chunks


def ingest_naive(doc_key: str, size: int = 1000, overlap: int = 200) -> list[Chunk]:
    """Baseline for comparison: dump the text, cut every `size` characters. No layout, no headings, no tables."""
    pdf = pymupdf.open(PDF_DIR / DOCS[doc_key]["file"])
    full, page_at = "", []
    for p in pdf:
        t = p.get_text()
        page_at.append((len(full), p.number + 1))
        full += t + "\n"
    out, i = [], 0
    while i < len(full):
        txt = full[i:i + size].strip()
        pg = max(pn for off, pn in page_at if off <= i)
        if txt:
            out.append(Chunk(make_id(doc_key, "naive", i), doc_key, txt, pg, pg))
        i += size - overlap
    return out
