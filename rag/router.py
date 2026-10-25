"""Query analysis: turns a question into metadata constraints (region / chapter / part / element kind).

Cheap, deterministic rules instead of an extra LLM call: the World Bank report has a closed vocabulary of regions
and chapters, so rules are faster, free and easy to debug. Returns constraints as Chroma `where` dicts plus a
human-readable explanation that is surfaced in the UI/eval for transparency.
"""
from __future__ import annotations
import re

REGIONS = {
    "East Asia and Pacific": [r"east asia", r"\beap\b"],
    "Europe and Central Asia": [r"europe and central asia", r"\beca\b", r"central asia"],
    "Latin America and the Caribbean": [r"latin america", r"caribbean", r"\blac\b"],
    "Middle East, North Africa, Afghanistan, and Pakistan": [r"middle east", r"north africa", r"\bmena", r"afghanistan", r"pakistan"],
    "South Asia": [r"south asia", r"\bsar\b"],
    "Sub-Saharan Africa": [r"sub-?saharan", r"\bssa\b", r"\bafrica\b"],
}

CHAPTER_TOPICS = {  # soft hints only (used as a boost, never as a hard filter)
    1: [r"global outlook", r"global growth", r"global economy"],
    2: [r"regional outlook"],
    3: [r"sovereign debt", r"debt levels", r"interest rates", r"government debt"],
    4: [r"fiscal policy", r"commodity price", r"price swings", r"volatility"],
}

NUMERIC_Q = re.compile(r"\b(how (much|many)|what (percent|percentage|share|number|total)|total|percent|%|kg|kwh|watt|amount|growth|rate)\b", re.I)


def analyze(query: str, doc: str | None) -> dict:
    q = query.lower()
    where_hard: list[tuple[dict, str]] = []     # (chroma where, explanation)
    soft: dict = {}
    if doc == "gep":
        m = re.search(r"\bchapter\s*(\d)\b|\bch\.?\s*(\d)\b", q)
        if m:
            n = int(m.group(1) or m.group(2))
            where_hard.append(({"chapter_no": n}, f"chapter {n}"))
        if re.search(r"executive summary", q):
            where_hard.append(({"part": "Executive Summary"}, "Executive Summary"))
        for region, pats in REGIONS.items():
            if any(re.search(p, q) for p in pats):
                where_hard.append(({"region": region}, f"region: {region}"))
                break
        for n, pats in CHAPTER_TOPICS.items():
            if any(re.search(p, q) for p in pats):
                soft["chapter_no"] = n
                break
    if doc == "imac":
        if re.search(r"foot ?note|end ?note|\bnote\b", q):
            where_hard.append(({"kind": "footnote"}, "footnotes"))
        if NUMERIC_Q.search(query):
            soft["kinds"] = ["table", "chart", "callout"]
    return {"hard": where_hard, "soft": soft,
            "explain": "; ".join(e for _, e in where_hard) or "no explicit constraint"}
