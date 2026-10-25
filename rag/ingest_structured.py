"""Use case 2 - World Bank Global Economic Prospects (200 pages, chapters > sections > sub-sections).

Parsing   : column-aware reading order; a heading state machine driven by font family/size
            (Helvetica = headings, Garamond = body) tracks chapter / region / box / section / sub-section.
Chunking  : *hierarchical* - text is only ever packed inside one leaf section (never across headings), and each
            chunk carries its full section path + chapter/region/box metadata. Tables are rebuilt from word geometry,
            figures become caption+panel-title+note chunks (axis labels are dropped as noise), references are skipped.
Retrieval : metadata constraints (region / chapter / executive summary) are applied by the router, see router.py.
"""
from __future__ import annotations
import re, collections
import pymupdf
from .common import Chunk, make_id, n_words, PDF_DIR, DOCS
from . import layout
from .ingest_narrative import pack_units

CHAPTER_TITLES = {1: "Global Outlook", 2: "Regional Outlooks",
                  3: "A Rising Challenge: Sovereign Debt Levels and Interest Rates in EMDEs",
                  4: "Navigating Volatility: Fiscal Policy and Commodity Price Swings"}
REGION_CANON = {
    "east asia and pacific": "East Asia and Pacific",
    "europe and central asia": "Europe and Central Asia",
    "latin america and the caribbean": "Latin America and the Caribbean",
    "middle east, north africa, afghanistan, and pakistan": "Middle East, North Africa, Afghanistan, and Pakistan",
    "south asia": "South Asia",
    "sub-saharan africa": "Sub-Saharan Africa",
}
SKIP_PARTS = {"contents", "summary of contents", "abbreviations", "acknowledgments"}
CAPTION = re.compile(r"^(TABLE|FIGURE|BOX)\s+([A-Z]?\d+(?:\.\d+)*)\b\s*(.*)", re.S)
PART_NAMES = {"executive summary": "Executive Summary", "foreword": "Foreword", "contents": "contents",
              "summary of contents": "summary of contents", "abbreviations": "abbreviations",
              "acknowledgments": "acknowledgments"}


def _helv(b): return b.font.startswith("Helvetica")


# The PDF's "Th" ligature glyph is extracted without the "h": "Te global economy" -> "The global economy".
_TH = {"Te": "The", "Tis": "This", "Tese": "These", "Tey": "They", "Tat": "That", "Teir": "Their", "Tere": "There",
       "Trough": "Through", "Tird": "Third", "Tough": "Though", "Tose": "Those", "Tus": "Thus"}
_TH_RE = re.compile(r"\b(" + "|".join(sorted(_TH, key=len, reverse=True)) + r")\b")


def fix_th(t: str) -> str:
    return _TH_RE.sub(lambda m: _TH[m.group(1)], t)


def heading_level(b: layout.Block) -> int:
    w = len(b.text.split())
    t = b.text.strip()
    if w > 14 or t.endswith((".", ",", ";", ":")) or CAPTION.match(t):
        return 0
    if _helv(b) and b.bold and b.size >= 15.5:
        return 1
    if _helv(b) and b.bold and b.size >= 13.5:
        return 2
    if _helv(b) and not b.bold and 10.9 <= b.size <= 11.6 and w <= 10:
        return 3
    if "BoldItalic" in b.font and 10.5 <= b.size <= 11.6 and w <= 12:
        return 3
    return 0


class State:
    def __init__(self):
        self.part = "front"; self.chapter_no = 0; self.region = ""; self.box = ""
        self.l1 = self.l2 = self.l3 = ""; self.refs = False

    def path(self) -> list[str]:
        head = (f"Chapter {self.chapter_no}: {CHAPTER_TITLES[self.chapter_no]}" if self.chapter_no
                else self.part if self.part not in ("front", "Chapter") else "")
        p = [head] if head else []
        if self.box:
            p.append(self.box)
        for x in (self.l1, self.l2, self.l3):
            if x and x not in p:
                p.append(x)
        return p

    def meta(self) -> dict:
        return {"chapter_no": self.chapter_no, "part": ("Chapter" if self.chapter_no else self.part),
                "region": self.region, "box": self.box.split(" ", 2)[0] + " " + self.box.split(" ", 2)[1] if self.box else ""}


def _table_chunks(doc_key, page, cap_block, next_y, state, headers_set) -> list[Chunk]:
    """Rebuild one table from word geometry: only small Helvetica text below the caption and above the next caption."""
    small = [b for b in layout.page_blocks(page)
             if b.size <= 8.6 and _helv(b) and b.y0 >= cap_block.y1 - 2 and b.y0 < next_y and b.y0 < page.rect.height * 0.93]
    if not small:
        return []
    clip = pymupdf.Rect(min(b.x0 for b in small) - 2, cap_block.y1 - 2, max(b.x1 for b in small) + 2, max(b.y1 for b in small) + 2)
    rows = layout.words_to_rows(page.get_text("words", clip=clip), y_tol=2.6)
    lines, header = [], ""
    out = []
    for r in rows:
        cells = [c[2] for c in layout.merge_cells(r, gap=6.5)]
        line = " | ".join(cells)
        if len(cells) >= 3 and not re.search(r"\d", line) and sum(len(c) for c in cells) / len(cells) < 4:
            continue                                      # garbled glyph fragments from decorative header boxes
        if re.search(r"\b\w \w \w\b", line):
            continue                                      # 's a o ecas su': glyph-by-glyph fragments
        if len(cells) >= 3 and sum(1 for c in cells if len(c) <= 2 and not c.isdigit()) >= len(cells) / 2:
            continue
        if re.search(r"\b20\d\d[ef]?\b|\b20\d\d/\d\d", line) and len(cells) >= 4 and not re.search(r"[A-Za-z]{4,}", re.sub(r"Percentage|points?|from|January|projections", "", line)):
            header = line
        lines.append(line)
    cap = re.sub(r"\s+", " ", cap_block.text.strip())
    buf, words, hdr_for_chunk = [], 0, ""
    def emit():
        nonlocal buf, words
        if buf:
            txt = cap + "\n" + (("Columns: " + hdr_for_chunk + "\n") if hdr_for_chunk else "") + "\n".join(buf)
            out.append(Chunk(make_id(doc_key, "tbl", page.number, len(out), cap[:30]), doc_key, txt, page.number + 1, page.number + 1,
                             state.path(), "table", None, state.meta()))
        buf, words = [], 0
    for ln in lines:
        if re.search(r"\b20\d\d[ef]?\b|\b20\d\d/\d\d", ln) and ln == header:
            hdr_for_chunk = ln
        buf.append(ln); words += n_words(ln)
        if words > 260:
            emit()
    emit()
    return out


def ingest(doc_key: str = "gep") -> list[Chunk]:
    pdf = pymupdf.open(PDF_DIR / DOCS[doc_key]["file"])
    headers = layout.running_headers(pdf)
    st = State()
    chunks: list[Chunk] = []
    units: list[tuple[str, int]] = []
    sect_key = None

    def flush():
        nonlocal units
        if units:
            path, meta = st_snapshot
            for text, p0, p1 in pack_units(units, target=230, hard_max=330):
                if n_words(text) >= 15:
                    chunks.append(Chunk(make_id(doc_key, len(chunks), text[:40]), doc_key, text, p0, p1, list(path), "text", None, dict(meta)))
        units = []

    st_snapshot = (st.path(), st.meta())

    for page in pdf:
        pn = page.number + 1
        if pn <= 6:
            continue                                              # covers / inside-cover
        blocks = layout.reading_order(layout.clean_blocks(page, layout.page_blocks(page), headers), page.rect.width)
        captions = [b for b in blocks if _helv(b) and b.bold and CAPTION.match(b.text.strip()) and b.size >= 9.5]
        fig = None

        def close_fig():
            nonlocal fig
            if fig and len(fig["parts"]) >= 1:
                txt = fig["cap"] + "\n" + "\n".join(fig["parts"])
                chunks.append(Chunk(make_id(doc_key, "fig", pn, len(chunks)), doc_key, txt, pn, pn, fig["path"], "chart", None, fig["meta"]))
            fig = None

        for b in blocks:
            b.text = fix_th(b.text)
            t = b.text.strip()
            # ---- chapter / part markers -------------------------------------------------
            m = re.fullmatch(r"CHAPTER\s+(\d)", t)
            if b.size >= 24 and m:
                flush(); close_fig()
                st.chapter_no = int(m.group(1)); st.part = "Chapter"; st.region = st.box = st.l1 = st.l2 = st.l3 = ""; st.refs = False
                st_snapshot = (st.path(), st.meta()); continue
            if b.size >= 24:
                key = t.lower().strip()
                if "cond" in b.font.lower() and key in PART_NAMES:
                    flush(); close_fig()
                    st.part = PART_NAMES[key]; st.chapter_no = 0; st.region = st.box = st.l1 = st.l2 = st.l3 = ""; st.refs = False
                    st_snapshot = (st.path(), st.meta())
                elif re.search(r"statistical (appendix|annex)", key):
                    flush(); close_fig()
                    st.part = "Statistical Appendix"; st.chapter_no = 0; st.region = st.box = st.l1 = st.l2 = st.l3 = ""; st.refs = False
                    st_snapshot = (st.path(), st.meta())
                continue                                           # chapter title text itself
            if st.part in SKIP_PARTS:
                continue
            # ---- captions (BOX / FIGURE / TABLE) ------------------------------------------
            cm = CAPTION.match(t) if (_helv(b) and b.bold and b.size >= 9.5) else None
            if cm:
                kind = cm.group(1)
                if kind == "BOX":
                    flush(); close_fig()
                    st.box = re.sub(r"\s*\(continued\)\s*", "", f"Box {cm.group(2)} {re.sub(chr(10), ' ', cm.group(3)).strip()}").strip()
                    st.l1 = st.l2 = st.l3 = ""; st.refs = False
                    st_snapshot = (st.path(), st.meta())
                elif kind == "FIGURE":
                    close_fig()
                    fig = {"cap": re.sub(r"\s+", " ", t), "parts": [], "path": st.path(), "meta": st.meta()}
                elif kind == "TABLE":
                    close_fig()
                    nxt = min([c.y0 for c in captions if c.y0 > b.y0 + 5], default=page.rect.height)
                    chunks += _table_chunks(doc_key, page, b, nxt, st, headers)
                continue
            # ---- small text: figure panel titles / notes (chart axis labels are dropped) ---------
            if b.size < 8.6:
                if fig and len(t) > 12 and (b.bold or re.match(r"(Sources?|Notes?)\b", t)) and not re.fullmatch(r"[\d\s.,%\-–]+", t):
                    fig["parts"].append(re.sub(r"\s+", " ", t))
                continue
            # ---- headings ----------------------------------------------------------------
            lvl = heading_level(b)
            if lvl:
                flush(); close_fig()
                key = re.sub(r"\s+", " ", t).lower()
                if lvl == 1:
                    st.box = ""                                    # a section heading always closes a box
                    st.l1, st.l2, st.l3 = re.sub(r"\s+", " ", t), "", ""
                    st.region = REGION_CANON.get(key, "") if st.chapter_no == 2 else ""
                    st.refs = key == "references"
                elif lvl == 2:
                    st.l2, st.l3 = re.sub(r"\s+", " ", t), ""
                    st.refs = key == "references"
                else:
                    st.l3 = re.sub(r"\s+", " ", t)
                st_snapshot = (st.path(), st.meta()); continue
            if st.refs or b.size < 9.5:
                continue
            if re.fullmatch(r"[\W\d_]+", t):
                continue
            if not units:
                st_snapshot = (st.path(), st.meta())
            units.append((t, pn))
        close_fig()
    flush()
    return chunks
