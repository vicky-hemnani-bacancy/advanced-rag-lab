"""Evaluation set.  `official` = the 9 sample questions from the exercise brief; the rest are extra probes that target the
specific failure modes of each document type (distractor numbers, region/chapter confusion, tables, charts, footnotes).

Each question:
  must      : list of regex groups; every group must match the answer (AND of ORs)   -> answer correctness
  must_not  : regexes that must NOT appear in the answer (wrong-section / wrong-number leakage)
  pages     : acceptable source pages (retrieval hit); `page_range` alternative for 'what does chapter X say' questions
  abstain   : True for out-of-scope questions (the system must say it cannot find the answer)
"""

Q = [
    # ---------------------------------------------------------------- GPO: plain narrative
    dict(id="gpo-1", doc="gpo", official=True, q="How many depository libraries did GPO staff visit in FY 2018?",
         must=[r"\b166\b"], must_not=[r"1,133"], pages=[4, 5, 21], note="distractor: 1,133 libraries nationwide"),
    dict(id="gpo-2", doc="gpo", official=True, q="What new digital system replaced FDsys, and when was it fully deployed?",
         must=[r"govinfo", r"2018"], pages=[4, 5, 22, 10, 39, 21], note="distractor: beta ended Dec 2017"),
    dict(id="gpo-3", doc="gpo", official=True,
         q="How much did GPO procure in printing and information products in FY 2018 on behalf of federal agencies?",
         must=[r"375"], pages=[5, 13, 17, 23], note="distractor: $375.7M is revenue from procured printing"),
    dict(id="gpo-4", doc="gpo", q="How many titles and copies did GPO distribute to depository libraries in FY 2018?",
         must=[r"4,211", r"802,834"], pages=[5, 15, 16]),
    dict(id="gpo-5", doc="gpo", q="When was the govinfo website moved out of beta?",
         must=[r"December 2017"], pages=[22]),
    dict(id="gpo-6", doc="gpo", q="How many passports did GPO produce in FY 2018?",
         must=[r"15,901,600|15\.9 million|16 million"], pages=[14, 13, 18],
         note="stats page says 15,901,600; narrative (p18) says 16 million"),
    dict(id="gpo-7", doc="gpo", q="How many FDLP Academy webinars did GPO host and how many participants did they serve?",
         must=[r"\b85\b", r"10,\d{3}"], pages=[5, 21, 20]),
    dict(id="gpo-x", doc="gpo", q="Who won the 2022 FIFA World Cup?", abstain=True),

    # ---------------------------------------------------------------- GEP: long, structured
    dict(id="gep-1", doc="gep", official=True, q="What is the growth outlook for South Asia in this report?",
         must=[r"6\.3"], must_not=[r"\b4\.2 percent"], pages=[96, 97, 98], note="region confusion: EAP is 4.2%"),
    dict(id="gep-2", doc="gep", official=True, q="What does Chapter 3 say about sovereign debt in developing economies?",
         must=[r"interest rate|yield|spread|borrowing cost", r"debt"], page_range=[107, 142], note="must stay inside Chapter 3"),
    dict(id="gep-3", doc="gep", official=True,
         q="According to the executive summary, what are the main risks to the global outlook?",
         must=[r"downside", r"hostilit|conflict|escalat"], pages=[19], note="same text also in Ch.1 summary (p25)"),
    dict(id="gep-4", doc="gep", q="What is the growth outlook for East Asia and Pacific in 2026?",
         must=[r"4\.2"], must_not=[r"\b6\.3 percent"], pages=[81, 82]),
    dict(id="gep-5", doc="gep", q="How fast did growth in Sub-Saharan Africa firm in 2025?",
         must=[r"4\.1"], pages=[99]),
    dict(id="gep-6", doc="gep", q="What is global growth projected to be in 2026 and how does it compare with 2025?",
         must=[r"2\.5", r"2\.9"], page_range=[19, 60]),
    dict(id="gep-7", doc="gep", q="How low could global growth fall in 2026 if energy disruptions are more severe than assumed?",
         must=[r"1\.3"], page_range=[19, 60]),
    dict(id="gep-8", doc="gep", q="In the South Asia forecast summary table, what is projected EMDE SAR GDP growth for 2027?",
         must=[r"6\.9"], pages=[98], note="answer lives in a table"),
    dict(id="gep-x", doc="gep", q="What is the projected GDP growth of Brazil in the year 2031?", abstain=True),

    # ---------------------------------------------------------------- iMac: charts, tables, footnotes
    dict(id="imac-1", doc="imac", official=True,
         q="How much less energy does iMac use compared to the ENERGY STAR requirement?",
         must=[r"58 ?(percent|%)"], pages=[7, 12]),
    dict(id="imac-2", doc="imac", official=True,
         q="What is the total carbon footprint of the iMac, and how much of that comes from product use versus manufacturing?",
         must=[r"346", r"45 ?(%|percent)", r"50 ?(%|percent)"], pages=[10, 2], note="chart total + table split"),
    dict(id="imac-3", doc="imac", official=True,
         q="What material is the iMac stand made from, and what percentage of it is recycled?",
         must=[r"alumin", r"100 ?(%|percent)"], pages=[4, 1, 2]),
    dict(id="imac-4", doc="imac", q="What is the carbon footprint of the iMac (four ports) 512GB configuration?",
         must=[r"391"], pages=[10]),
    dict(id="imac-5", doc="imac", q="What is the power consumption of iMac in sleep mode at 115V?",
         must=[r"0\.57"], pages=[12], note="table; built-in extractor corrupts decimals"),
    dict(id="imac-6", doc="imac", q="What percentage of the fiber packaging is recycled content?",
         must=[r"76"], pages=[6]),
    dict(id="imac-7", doc="imac", q="What were the baseline emissions before reductions in the carbon chart, and how large is the reduction?",
         must=[r"445", r"99"], pages=[2], note="chart"),
    dict(id="imac-8", doc="imac", q="Which power adapter was used when testing iMac against the ENERGY STAR requirements?",
         must=[r"143 ?W"], pages=[12], note="footnote 18"),
    dict(id="imac-9", doc="imac", q="What share of manufacturing electricity comes from supplier low-carbon energy projects?",
         must=[r"20 ?(%|percent)"], pages=[5, 1, 12]),
    dict(id="imac-x", doc="imac", q="How many iMac units did Apple sell worldwide in 2024?", abstain=True),
]
