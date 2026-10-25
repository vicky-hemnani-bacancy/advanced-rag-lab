"""Layout-aware PDF reading: column-aware reading order, header/footer removal, table rows from word geometry."""
from __future__ import annotations
import re, collections
from dataclasses import dataclass
import pymupdf


@dataclass
class Block:
    page: int
    text: str
    bbox: tuple
    size: float          # dominant font size of the block
    bold: bool
    font: str
    sup_refs: list[str]  # superscript footnote markers found inside the block

    @property
    def x0(self): return self.bbox[0]
    @property
    def y0(self): return self.bbox[1]
    @property
    def x1(self): return self.bbox[2]
    @property
    def y1(self): return self.bbox[3]


def _is_bold(font: str, flags: int) -> bool:
    return bool(flags & 16) or "Bold" in font or "Semibold" in font or "Black" in font


def _norm(t: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", t.strip().lower()))


_LIG = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", " ": " ", "­": ""}


def fix_ligatures(t: str) -> str:
    for k, v in _LIG.items():
        t = t.replace(k, v)
    return t


def dehyphenate(lines: list[str]) -> str:
    out = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if out.endswith("-") and ln[:1].islower() and not out.endswith(" -"):
            out = out[:-1] + ln
        else:
            out = (out + " " + ln) if out else ln
    return re.sub(r"\s+", " ", out).strip()


def page_blocks(page: pymupdf.Page, mark_superscripts: bool = False) -> list[Block]:
    """Text blocks of one page (unordered). Superscripts become [^n] markers when requested."""
    out = []
    d = page.get_text("dict")
    for b in d["blocks"]:
        if b.get("type") != 0:
            continue
        lines, sizes, fonts, bold_chars, tot, sup = [], collections.Counter(), collections.Counter(), 0, 0, []
        for l in b["lines"]:
            parts = []
            max_sz = max((s["size"] for s in l["spans"]), default=0)
            for s in l["spans"]:
                t = s["text"]
                if not t.strip():
                    parts.append(t)
                    continue
                is_sup = bool(s["flags"] & 1)          # true superscripts only (subscripts like CO2e must stay text)
                if mark_superscripts and is_sup and t.strip().isdigit():
                    parts.append(f"[^{t.strip()}]")
                    sup.append(t.strip())
                else:
                    parts.append(t)
                    sizes[round(s["size"], 1)] += len(t)
                    fonts[s["font"]] += len(t)
                    if _is_bold(s["font"], s["flags"]):
                        bold_chars += len(t)
                    tot += len(t)
            lines.append("".join(parts))
        text = fix_ligatures(dehyphenate(lines))
        if not text:
            continue
        out.append(Block(page.number + 1, text, tuple(b["bbox"]),
                         sizes.most_common(1)[0][0] if sizes else 0,
                         tot > 0 and bold_chars / tot > 0.6,
                         fonts.most_common(1)[0][0] if fonts else "", sup))
    return out


def reading_order(blocks: list[Block], page_w: float) -> list[Block]:
    """Order blocks: full-width blocks split the page into bands; inside a band read left column then right."""
    mid = page_w / 2

    def full(b):
        return (b.x1 - b.x0) > 0.62 * page_w or (b.x0 < mid * 0.55 and b.x1 > mid * 1.45)

    ordered, band = [], []

    def flush():
        left = sorted([b for b in band if (b.x0 + b.x1) / 2 < mid], key=lambda b: (b.y0, b.x0))
        right = sorted([b for b in band if (b.x0 + b.x1) / 2 >= mid], key=lambda b: (b.y0, b.x0))
        ordered.extend(left + right)
        band.clear()

    for b in sorted(blocks, key=lambda b: (b.y0, b.x0)):
        if full(b):
            flush()
            ordered.append(b)
        else:
            band.append(b)
    flush()
    return ordered


def running_headers(doc: pymupdf.Document, top: float = 0.075, bottom: float = 0.925, min_frac: float = 0.2) -> set[str]:
    """Normalised texts that repeat in the top/bottom margins of many pages (running headers/footers/page numbers)."""
    cnt = collections.Counter()
    for p in doc:
        seen = set()
        for b in p.get_text("blocks"):
            if b[6] != 0:
                continue
            if b[3] < p.rect.height * top or b[1] > p.rect.height * bottom:
                seen.add(_norm(b[4]))
        cnt.update(seen)
    n = max(1, len(doc))
    return {t for t, c in cnt.items() if c >= max(3, n * min_frac)}


def clean_blocks(page: pymupdf.Page, blocks: list[Block], headers: set[str], top=0.075, bottom=0.925) -> list[Block]:
    H = page.rect.height
    keep = []
    for b in blocks:
        in_margin = b.y1 < H * top or b.y0 > H * bottom
        if in_margin and (_norm(b.text) in headers or re.fullmatch(r"[\d\s|ivxlc]+", b.text.strip().lower() or "x")):
            continue
        keep.append(b)
    return keep


def words_to_rows(words, y_tol: float = 3.0):
    """Group pymupdf words (x0,y0,x1,y1,text,...) into rows; each row is a list of (x0, x1, text) sorted by x."""
    ws = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    rows, cur, cy = [], [], None
    for w in ws:
        yc = (w[1] + w[3]) / 2
        if cy is None or abs(yc - cy) <= y_tol:
            cur.append(w)
            cy = yc if cy is None else (cy * (len(cur) - 1) + yc) / len(cur)
        else:
            rows.append(cur)
            cur, cy = [w], yc
    if cur:
        rows.append(cur)
    return [sorted([(w[0], w[2], w[4]) for w in r], key=lambda t: t[0]) for r in rows]


def merge_cells(row, gap: float = 9.0):
    """Merge neighbouring words closer than `gap` pt into one cell (so 'Idle—Display On' stays one cell)."""
    cells, cur = [], None
    for x0, x1, t in row:
        if cur and x0 - cur[1] <= gap:
            cur = [cur[0], x1, cur[2] + " " + t]
        else:
            if cur:
                cells.append(cur)
            cur = [x0, x1, t]
    if cur:
        cells.append(cur)
    return cells
