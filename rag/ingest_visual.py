"""Use case 3 - Apple iMac Product Environmental Report (12 pages: charts, icon call-outs, tables, footnotes).

Facts live outside plain paragraphs, so the pipeline has one extractor per element type:
  * text      : page text with inline footnote markers  [^18]  and the footnote text appended (fact + its qualifier stay together)
  * callouts  : short icon/stat blocks ("100 percent recycled aluminum in the stand") get their own high-precision chunk
  * tables    : structure from pymupdf cell geometry, text re-read from PDF spans (the built-in extractor drops decimal
                points: "0.27W" -> "027W"), emitted as a grid AND as "row facts" sentences
  * charts    : vision model reads the rendered page; every number is cross-checked against the PDF text layer and
                flagged as verified/unverified, chunk is labelled machine-read so the answer prompt can down-weight it
  * footnotes : endnotes parsed into their own chunks, linked back to the sentences that cite them
"""
from __future__ import annotations
import re, json, base64, collections, hashlib
import pymupdf
from .common import Chunk, make_id, n_words, PDF_DIR, DOCS, CACHE
from . import layout, llm

VISION_PROMPT = (
    "This is one page of Apple's iMac Product Environmental Report. Extract ONLY information that is shown in "
    "graphics (charts, bars, donuts, icons with big numbers, diagrams) and not in ordinary paragraphs.\n"
    "For each graphic give: its title; every label and every number exactly as printed; and the relationships "
    "(which bar/segment is larger, what the arrows/brackets connect, totals vs parts).\n"
    "Rules: copy numbers exactly; if a number is not legible write 'unreadable' - never estimate; do not invent "
    "values that are not printed; if the page has no graphic carrying data, answer exactly NONE.\n"
    "Output a compact bullet list."
)
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _nums(s: str) -> set[str]:
    return {m.replace(",", "").rstrip(".") for m in _NUM.findall(s)}


# ---------------------------------------------------------------- vision (cached)
def caption_page(page: pymupdf.Page, dpi: int = 110) -> str:
    CACHE.mkdir(exist_ok=True)
    key = hashlib.md5((VISION_PROMPT + llm.VISION_MODEL).encode()).hexdigest()[:8]
    f = CACHE / f"vision_imac_p{page.number + 1}_{key}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))["caption"]
    b64 = base64.b64encode(page.get_pixmap(dpi=dpi).tobytes("png")).decode()
    msg = [{"role": "user", "content": [{"type": "text", "text": VISION_PROMPT},
                                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]}]
    cap = llm.chat(msg, model=llm.VISION_MODEL, max_tokens=1400)
    f.write_text(json.dumps({"caption": cap}), encoding="utf-8")
    return cap


# ---------------------------------------------------------------- endnotes
def parse_endnotes(pdf: pymupdf.Document) -> dict[int, str]:
    text = ""
    for p in pdf:
        t = p.get_text()
        if "Endnotes" in t[:200] or text:
            text += "\n" + t
    start = text.find("Endnotes")
    text = text[start:] if start >= 0 else text
    text = re.split(r"\n\s*Mode\s*\n\s*Power consumption", text)[0]          # the power table follows note 19
    ms = list(re.finditer(r"(?m)^[\t ]*(\d{1,2})[\t ]+(?=\S)", text))
    notes, expect = {}, 1
    sel = []
    for m in ms:
        if int(m.group(1)) == expect:
            sel.append(m); expect += 1
    for i, m in enumerate(sel):
        end = sel[i + 1].start() if i + 1 < len(sel) else len(text)
        body = re.sub(r"\s+", " ", text[m.end():end]).strip()
        notes[int(m.group(1))] = layout.fix_ligatures(body)
    return notes


# ---------------------------------------------------------------- tables
def cell_text(page: pymupdf.Page, bbox) -> str:
    """Text of one table cell re-read from spans; superscripts become [^n]."""
    d = page.get_text("dict", clip=pymupdf.Rect(bbox))
    lines = []
    for b in d["blocks"]:
        for l in b.get("lines", []):
            parts = []
            for s in l["spans"]:
                t = s["text"]
                if s["flags"] & 1 and t.strip().isdigit():
                    parts.append(f"[^{t.strip()}]")
                else:
                    parts.append(t)
            lines.append("".join(parts).strip())
    return layout.fix_ligatures(re.sub(r"\s+", " ", " ".join(x for x in lines if x))).strip()


def table_rows(page: pymupdf.Page, table) -> list[list[str]]:
    rows = []
    for r in table.rows:
        rows.append([cell_text(page, c) if c else "" for c in r.cells])
    rows = [r for r in rows if any(r)]
    start = 1 if rows and sum(1 for c in rows[0] if c) == 1 else 0          # spanning title row does not define columns
    keep = [j for j in range(max(len(r) for r in rows)) if any(j < len(r) and r[j] for r in rows[start:])]
    return [[r[j] if j < len(r) else "" for j in keep] for r in rows]


def table_chunk(doc_key, page, title_hint, rows, section) -> Chunk | None:
    if len(rows) < 2:
        return None
    title = title_hint
    if sum(1 for c in rows[0] if c) == 1:                                    # a spanning title row
        title = rows[0][next(i for i, c in enumerate(rows[0]) if c)]
        rows = rows[1:]
    header, body = rows[0], rows[1:]
    if title == title_hint and header and header[0]:
        title = f"{title_hint}: {header[0]}"                          # distinguish several tables on one page
    grid = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)] + ["| " + " | ".join(r) + " |" for r in body]
    facts = []
    for r in body:
        label = r[0].lstrip('\u2022 ').strip()
        vals = [f"{header[j]} = {r[j]}" if j < len(header) and header[j] else r[j] for j in range(1, len(r)) if r[j]]
        facts.append(f"- {label}: " + "; ".join(vals) if vals else f"- {label}")
    txt = f"Table: {title} (page {page.number + 1})\n" + "\n".join(grid) + "\nRow facts:\n" + "\n".join(facts)
    return Chunk(make_id(doc_key, "tbl", page.number, txt[:120], len(txt)), doc_key, txt, page.number + 1, page.number + 1,
                 section + [title], "table", None, {"table_title": title})


# ---------------------------------------------------------------- main
def ingest(doc_key: str = "imac", use_vision: bool = True) -> list[Chunk]:
    pdf = pymupdf.open(PDF_DIR / DOCS[doc_key]["file"])
    headers = layout.running_headers(pdf, min_frac=0.3)
    notes = parse_endnotes(pdf)
    chunks: list[Chunk] = []
    cited_in: dict[int, list[tuple[int, str]]] = collections.defaultdict(list)    # note -> [(page, sentence)]

    for page in pdf:
        pn = page.number + 1
        blocks = layout.clean_blocks(page, layout.page_blocks(page, mark_superscripts=True), headers)
        blocks = [b for b in blocks if not re.fullmatch(r"iMac\s*\|\s*Product Environmental Report", b.text.strip())]
        if pn == 11:
            continue                                                       # endnotes page -> handled as footnote chunks
        ordered = layout.reading_order(blocks, page.rect.width)
        sizes = collections.Counter()
        for b in ordered:
            sizes[b.size] += len(b.text)
        body = sizes.most_common(1)[0][0] if sizes else 10
        big = [b for b in ordered if b.size >= max(body * 1.5, 16) and len(b.text.split()) <= 14]
        title = re.sub(r"\s+", " ", big[0].text).strip() if big else (f"Page {pn}")
        section = [title]

        # ---- tables (cells from geometry, text from spans) ----
        tab_boxes = []
        try:
            found = page.find_tables().tables
        except Exception:
            found = []
        for t in found:
            rows = table_rows(page, t)
            c = table_chunk(doc_key, page, title, rows, [])
            if c:
                chunks.append(c)
                tab_boxes.append(pymupdf.Rect(t.bbox))

        def in_table(b):
            r = pymupdf.Rect(b.bbox)
            return any(tb.intersects(r) and (tb & r).get_area() > 0.5 * r.get_area() for tb in tab_boxes)

        body_blocks = [b for b in ordered if not in_table(b)]
        if pn == 12:                                                       # page 12 = endnotes 17-19 + legal + power table
            body_blocks = []
        page_text = "\n".join(b.text for b in body_blocks)

        # ---- footnote bookkeeping: which sentence cites which note ----
        for b in body_blocks:
            for sent in re.split(r"(?<=[.!?])\s+", b.text):
                for n in re.findall(r"\[\^(\d+)\]", sent):
                    cited_in[int(n)].append((pn, re.sub(r"\[\^\d+\]", "", sent).strip()))

        # ---- page text chunk(s), footnote text appended ----
        paras = [b.text for b in body_blocks]
        if paras:
            groups, cur, w = [], [], 0
            for p_ in paras:
                if cur and w + n_words(p_) > 330:
                    groups.append(cur); cur, w = [], 0
                cur.append(p_); w += n_words(p_)
            if cur:
                groups.append(cur)
            for g in groups:
                txt = "\n".join(g)
                refs = sorted({int(x) for x in re.findall(r"\[\^(\d+)\]", txt)})
                if refs:
                    txt += "\nFootnotes cited in this passage:\n" + "\n".join(f"[^{n}] {notes[n]}" for n in refs if n in notes)
                if n_words(txt) >= 8:
                    chunks.append(Chunk(make_id(doc_key, "txt", pn, len(chunks)), doc_key, txt, pn, pn, section, "text", None, {"footnotes": refs}))

        # ---- call-outs: short stat / icon blocks ----
        short = [b.text for b in body_blocks if 3 <= n_words(b.text) <= 45 and (not big or b.size < big[0].size * 0.9)]
        if len(short) >= 2 and sum(n_words(x) for x in short) >= 40 and any(n_words(x) >= 6 for x in short):
            refs = sorted({int(x) for s in short for x in re.findall(r"\[\^(\d+)\]", s)})
            txt = "Key call-outs and statistics on this page:\n" + "\n".join(f"- {s}" for s in short)
            chunks.append(Chunk(make_id(doc_key, "call", pn), doc_key, txt, pn, pn, section, "callout", None, {"footnotes": refs}))

        # ---- charts / graphics via vision ----
        if use_vision and (pn <= 10 or pn == 12):
            cap = caption_page(page)
            has_chart = bool(re.search(r"\b(bars?|segments?|axis|pie|donut|legend|stacked)\b", cap or "", re.I))
            if cap and cap.strip().upper() != "NONE" and len(cap) > 40 and has_chart and len(_nums(cap)) >= 2:   # skip nav icons / table duplicates
                page_nums = _nums(page.get_text())
                found_n, miss_n = [], []
                for n in sorted(_nums(cap), key=lambda x: (len(x), x)):
                    if len(n) == 1:
                        continue
                    (found_n if n in page_nums else miss_n).append(n)
                txt = (f"Machine-read description of the charts/graphics on page {pn} ('{title}'). "
                       f"Read from the page image by a vision model; may contain errors - prefer text/table sources when they disagree.\n"
                       f"Numbers confirmed by the PDF text layer: {', '.join(found_n) or 'none'}. "
                       f"Numbers NOT confirmed by the text layer: {', '.join(miss_n) or 'none'}.\n{cap.strip()}")
                chunks.append(Chunk(make_id(doc_key, "vis", pn), doc_key, txt, pn, pn, section, "chart", None,
                                    {"unverified": ",".join(miss_n)}))

    # ---- footnote chunks, linked to the claims they qualify ----
    for n, body in notes.items():
        refs = cited_in.get(n, [])
        pages = sorted({p for p, _ in refs})
        claim = " ".join(f"On page {p}: \"{s[:220]}\"" for p, s in [r for r in refs if n_words(r[1]) >= 5][:3])
        txt = f"Footnote {n}" + (f" (cited on page {', '.join(map(str, pages))})" if pages else "") + f": {body}" + (f"\nThis footnote qualifies the claim: {claim}" if claim else "")
        chunks.append(Chunk(make_id(doc_key, "fn", n), doc_key, txt, 11 if n <= 16 else 12, 11 if n <= 16 else 12,
                            ["Endnotes"], "footnote", None, {"note": n}))
    return chunks
