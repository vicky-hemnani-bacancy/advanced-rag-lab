# Advanced RAG over three document types

One question-answering system, three PDFs with deliberately different shapes. The point of the exercise is that a
single "split into chunks, embed, search" recipe does not work for all of them, so each document gets a pipeline
designed around what makes it hard.

| # | Document | What makes it hard | What the pipeline does about it |
|---|---|---|---|
| 1 | GPO 2018 Annual Report (82 pp, narrative) | Facts sit inside sentences; near-duplicate numbers act as distractors (166 libraries *visited* vs 1,133 *total*; "$375 million" vs "$375.7 million") | Layout-aware parsing, sentence-boundary chunks, hybrid search, reranking, grounded answers |
| 2 | World Bank Global Economic Prospects, June 2026 (200 pp) | Chapters, regions, boxes, sub-sections; the same topic appears in several places (executive summary, Chapter 1, regional sections) | Hierarchical chunking from a font-driven heading state machine, section metadata, query routing to a region/chapter, table rebuild |
| 3 | Apple iMac Product Environmental Report (12 pp) | Facts live in charts, icon call-outs, tables and footnotes, not in paragraphs | Per-element extractors: table cells from geometry, footnote linking, call-out chunks, chart reading by a vision model with verification |

## Quick start (Windows)

```powershell
cd RagChallenge
py -3.14 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt

# .env  (not committed)
#   LLM_PROVIDER=gemini
#   LLM_MODEL=gemini-flash-lite-latest
#   GEMINI_API_KEY=...            # optional: GEMINI_API_KEY_2, _3 are rotated automatically on quota/overload errors
#   GROQ_API_KEY=...              # only needed for chart captioning at ingest time, or to use Groq models instead
#   VISION_MODEL=qwen/qwen3.8-27b

# The three PDFs are NOT included in this repository (they belong to their publishers: the U.S. GPO, the World Bank and
# Apple). Download them and point PDF_DIR in rag/common.py at the folder; the file names are listed in DOCS there.
# Copy .env.example to .env first.
.\.venv\Scripts\python ingest.py all            # advanced indexes  (about 10 min on 4 CPU cores)
.\.venv\Scripts\python ingest.py all --naive    # baseline indexes for comparison

# React UI
cd rag-ui; npm install; npm run build; cd ..    # builds rag-ui/dist, which the API serves at /
.\.venv\Scripts\python run_server.py            # app + API at http://localhost:8100
#   development with hot reload: run the server above, then `npm run dev` in rag-ui (http://localhost:5173, proxies /api)

.\.venv\Scripts\python evaluate.py --mode both            # evaluation (resumable with --resume)
.\.venv\Scripts\python make_report.py                     # refresh the results block below
```

Embeddings and reranking run locally on CPU (ONNX via fastembed). Only answer generation (Gemini by default) and chart
reading at ingest time call an API. Chart captions are cached in `cache/`, so re-ingesting does not call the vision model again.

## Pipeline

```
ingest:  PDF -> layout parsing -> document-specific chunking -> bge-base embeddings -> ChromaDB + BM25
query :  question -> router (region/chapter/kind constraints)
         -> dense top-40 + BM25 top-40 (+ constraint-restricted variants)
         -> Reciprocal Rank Fusion -> top-20 -> cross-encoder rerank -> routing boosts -> top-6
         -> neighbour expansion -> grounded prompt -> LLM -> citation cleanup -> number verification
```

Every chunk carries `doc, page, page_end, section_path, kind (text|table|chart|callout|footnote), meta`. The text that is
embedded and keyword-indexed has a contextual header (`[doc | Chapter 2 > South Asia > Outlook | page 96 | table]`), so
a bare number keeps its context.

### 1. GPO: narrative text (`rag/ingest_narrative.py`)
- Column-aware reading order; running headers and footers removed (margin text repeated on many pages).
- Sentences packed to about 220 words (hard max 320) with one-sentence overlap; each chunk keeps its page range.
- Headings are detected conservatively; "headings" that repeat on 4 or more pages are treated as running titles.

### 2. World Bank report: long and structured (`rag/ingest_structured.py`)
- A heading state machine reads font family and size (Helvetica = headings, Garamond = body) and tracks chapter,
  region, box, section, sub-section. The PDF bookmarks were **not** used for page numbers because they are off by one.
- Text is packed only **inside one leaf section**; chunks are never glued across headings. Metadata:
  `chapter_no, part, region, box`.
- Tables are rebuilt from word positions (rows by y, cells by x gap) with the year header repeated. Figures become
  caption + panel titles + notes; axis labels are dropped. References and front matter are skipped.
- The router turns "Chapter 3", "executive summary" and region names into metadata constraints. Constrained
  retrieval lists are fused with extra weight, and matching chunks get a score boost.
- Text repair: the PDF drops the "h" of its "Th" ligature ("Te global economy"); a word list repairs it. fi/fl ligatures
  are normalised.

### 3. iMac report: charts, tables, footnotes (`rag/ingest_visual.py`)
- **Tables:** PyMuPDF's `find_tables()` finds the cells, but its text corrupts decimals (`0.27W` became `027W`). Cell
  geometry is used for structure and the text is re-read from the PDF spans. Output is a grid plus "row facts"
  (`Sleep: 115V = 0.57W`).
- **Footnotes:** the 19 endnotes are parsed into their own chunks, linked back to the sentences that cite them, and
  appended to the passages that cite them. "58 percent less energy" travels with footnote 18 (how it was tested).
- **Call-outs:** short icon/stat blocks get their own chunk so "100 percent recycled aluminum in the stand" is easy to hit.
- **Charts:** pages are rendered and read by a vision model. Every number it returns is checked against the PDF text
  layer and the chunk records which numbers were confirmed. Chunks are labelled machine-read, and the answer prompt
  tells the LLM to prefer text and table sources. Only chunks that describe real chart structure with at least two
  numbers are kept; the repeated lifecycle-icon descriptions and table duplicates were pure noise.

### Shared retrieval and answering
- **Hybrid search:** `bge-base-en-v1.5` vectors (Chroma, HNSW cosine) plus BM25 with a tokenizer that keeps decimals.
  Merged with Reciprocal Rank Fusion (k=60), which needs no score normalisation.
- **Rerank:** `jina-reranker-v1-turbo-en` cross-encoder over the top 20. (`bge-reranker-base` was more accurate on
  paper but took about 27 s for 30 passages on this 4-core CPU, against about 5 s.)
- **Small-to-big:** the previous and next chunk of the same section are attached to the best narrative hits.
- **Grounded generation:** Gemini (`gemini-flash-lite-latest` by default; change it with `LLM_MODEL` in `.env`), temperature 0. The prompt requires `[S#]` citations, exact quoting, no
  derived figures, region/chapter separation, and a fixed "could not find this in the document" abstention.
- **Verification:** every number in an answer must occur in the sources it cites, otherwise it is flagged. This caught
  an answer that invented "≈156 kg / ≈173 kg" by multiplying percentages.
- **Abstain gate:** if the best reranker score is below `MIN_SCORE`, the LLM is not called (see limitations).

## Results

<!-- RESULTS:START -->
Evaluated on **27 questions**; **27** have a result in both pipelines and are compared below.

### Summary (answerable questions)

| Scope | Pipeline | n | Right page retrieved | Right page ranked #1 | MRR | Answer correct | Median time per question* |
|---|---|---|---|---|---|---|---|
| all | naive | 24 | 88% | 58% | 0.70 | 88% | 4s |
| all | advanced | 24 | 100% | 96% | 0.98 | 100% | 7s |
| gpo | naive | 7 | 100% | 71% | 0.86 | 100% | 2s |
| gpo | advanced | 7 | 100% | 100% | 1.00 | 100% | 5s |
| gep | naive | 8 | 75% | 62% | 0.69 | 62% | 6s |
| gep | advanced | 8 | 100% | 88% | 0.94 | 100% | 7s |
| imac | naive | 9 | 89% | 44% | 0.60 | 100% | 5s |
| imac | advanced | 9 | 100% | 100% | 1.00 | 100% | 7s |

Out-of-scope questions (should answer "not found"): advanced 3/3, naive 3/3.
Wrong-section leakage in advanced answers: 0. Answers flagged with numbers not found in their sources: 0.


\* Wall-clock time per question during the batch run (retrieval, reranking and the LLM call; the naive pipeline has no reranking). Generator model: `gemini-flash-lite-latest`.

### Per question

| id | official | question | naive | advanced | note |
|---|---|---|---|---|---|
| gpo-1 | yes | How many depository libraries did GPO staff visit in FY 2018? | correct | correct | distractor: 1,133 libraries nationwide |
| gpo-2 | yes | What new digital system replaced FDsys, and when was it fully deployed? | correct | correct | distractor: beta ended Dec 2017 |
| gpo-3 | yes | How much did GPO procure in printing and information products in FY 2018 on behalf of federal agencies? | correct | correct | distractor: $375.7M is revenue from procured printing |
| gpo-4 |  | How many titles and copies did GPO distribute to depository libraries in FY 2018? | correct | correct |  |
| gpo-5 |  | When was the govinfo website moved out of beta? | correct | correct |  |
| gpo-6 |  | How many passports did GPO produce in FY 2018? | correct | correct | stats page says 15,901,600; narrative (p18) says 16 million |
| gpo-7 |  | How many FDLP Academy webinars did GPO host and how many participants did they serve? | correct | correct |  |
| gpo-x |  | Who won the 2022 FIFA World Cup? | abstained | abstained |  |
| gep-1 | yes | What is the growth outlook for South Asia in this report? | correct | correct | region confusion: EAP is 4.2% |
| gep-2 | yes | What does Chapter 3 say about sovereign debt in developing economies? | right page, wrong answer | correct | must stay inside Chapter 3 |
| gep-3 | yes | According to the executive summary, what are the main risks to the global outlook? | wrong page | correct | same text also in Ch.1 summary (p25) |
| gep-4 |  | What is the growth outlook for East Asia and Pacific in 2026? | correct | correct |  |
| gep-5 |  | How fast did growth in Sub-Saharan Africa firm in 2025? | wrong page | correct |  |
| gep-6 |  | What is global growth projected to be in 2026 and how does it compare with 2025? | correct | correct |  |
| gep-7 |  | How low could global growth fall in 2026 if energy disruptions are more severe than assumed? | correct | correct |  |
| gep-8 |  | In the South Asia forecast summary table, what is projected EMDE SAR GDP growth for 2027? | correct | correct | answer lives in a table |
| gep-x |  | What is the projected GDP growth of Brazil in the year 2031? | abstained | abstained |  |
| imac-1 | yes | How much less energy does iMac use compared to the ENERGY STAR requirement? | correct | correct |  |
| imac-2 | yes | What is the total carbon footprint of the iMac, and how much of that comes from product use versus manufacturing? | correct | correct | chart total + table split |
| imac-3 | yes | What material is the iMac stand made from, and what percentage of it is recycled? | correct | correct |  |
| imac-4 |  | What is the carbon footprint of the iMac (four ports) 512GB configuration? | correct | correct |  |
| imac-5 |  | What is the power consumption of iMac in sleep mode at 115V? | correct | correct | table; built-in extractor corrupts decimals |
| imac-6 |  | What percentage of the fiber packaging is recycled content? | correct | correct |  |
| imac-7 |  | What were the baseline emissions before reductions in the carbon chart, and how large is the reduction? | correct | correct | chart |
| imac-8 |  | Which power adapter was used when testing iMac against the ENERGY STAR requirements? | correct | correct | footnote 18 |
| imac-9 |  | What share of manufacturing electricity comes from supplier low-carbon energy projects? | correct | correct |  |
| imac-x |  | How many iMac units did Apple sell worldwide in 2024? | abstained | abstained |  |
<!-- RESULTS:END -->

How to read this:
- The advanced pipeline retrieves 6 passages and the naive baseline 4, so "right page retrieved" is not perfectly
  like-for-like; "ranked #1" and answer correctness are the fairer comparisons.
- "Answer correct" is a regex check against verified ground truth (each answer must contain all required facts and none
  of the forbidden wrong-region/wrong-chapter numbers). It is stricter and cheaper than a human review, but it
  has been wrong before (see below).
- The naive baseline is plain text cut into 1000-character windows with dense search only: no layout handling, no
  metadata, no reranking, no checks. It is intentionally what a first attempt looks like.

## What went wrong along the way

These are the real defects found by inspecting data and results, not by assumption:
- **Naive chunking answered confidently wrong.** On the GPO report it said govinfo was "fully deployed in December
  2017" (that is when the beta ended) and quoted "$375.7 million" (revenue from procured printing) for the amount procured.
- **PDF bookmarks lied.** South Asia was bookmarked at page 95; its heading is on 96.
- **Extraction corrupts numbers.** PyMuPDF's table text turned `0.27W` into `027W`; the World Bank text lost the "h" in
  "Th" words (318 occurrences) and used fi/fl ligature characters, which hurts keyword matching.
- **A section state leaked.** The label "Box 3.1" stayed attached to later main-text sections until section headings
  were made to close it.
- **Vision is not trustworthy on its own.** It misread a footnote number, and it described the same lifecycle icon on
  six pages. It is now cross-checked and filtered.
- **Several "failures" were my test, not the system.** The judge did not normalise the narrow no-break spaces the
  model writes ("58 percent"), one expectation was wrong (the report says both "16 million" and "15,901,600"
  passports), and one check demanded the literal words "interest rate" when the answer said "bond yields". These were
  fixed in the checks, not by loosening the system.
- **Rate limits masked results.** Groq's free tier has two limits per model: 8,000 tokens per minute (prompt plus
  requested output) and **200,000 tokens per day**. Repeated evaluation runs used up the daily budget, after which every
  request failed with a generic "rate-limited" error until the real 429 message was logged. The client now shares one
  token budget across processes, records actual usage, fails fast with a readable message, and falls back to
  `gpt-oss-20b` then `qwen3.8-27b` when a model's daily allowance is gone. Requests were also shrunk (1,300-word
  context cap, 700-token output cap).
- **Long-lived server processes hung** twice on every request for reasons I did not identify (the same call worked
  in a fresh process, and in a freshly started server). The HTTP client now disables keep-alive reuse and uses a 45 s
  timeout; if a request ever hangs, restart with `python run_server.py`.

## Known limitations

- **`MIN_SCORE` was calibrated for a different reranker.** The abstain threshold (-3.0) was set for `bge-reranker-base`;
  with the Jina reranker it rarely triggers. In the evaluation, out-of-scope questions were refused by the LLM
  following the prompt, not by the score gate. It needs recalibration on negative examples.
- **Tuned on the questions it is graded on.** Routing boosts, thresholds and the choice of what to keep from vision
  were adjusted while looking at these questions. Treat the scores as a development result, not an unbiased
  estimate; a held-out question set would be needed for that.
- **Small test set.** About 30 questions with regex judging is a sanity check, not a benchmark.
- **The router is rule-based** and its region/chapter vocabulary is specific to the World Bank report. A new long
  document needs new rules or an LLM-based router.
- **Latency and quota.** On a 4-core CPU a question takes roughly 4 to 8 seconds end to end (reranking about 3 s).
  Free-tier API quotas (Gemini requests per minute, Groq tokens per day) limit heavy use; the client paces itself and
  rotates keys and models, but sustained load needs a paid tier or a local model.
- **Generator model.** The reported results were produced with `gemini-flash-lite-latest` only (fallbacks disabled for
  the run). The model name is stored with every answer in the evaluation results and shown as a badge on each answer in the UI. Results do depend on
  the model: an earlier full run with Groq's `gpt-oss-120b` (archived in `eval/archive_gpt-oss-120b/`) also gave 100% on
  the advanced pipeline but 75% for the naive baseline (88% with Gemini). The kinds of miss differed: with the earlier
  model the naive pipeline sometimes gave a confident wrong answer (for example "December 2017" for the govinfo
  deployment); with Gemini its misses on the World Bank report were refusals ("could not find this").
- **`gemini-flash-latest` was unreliable** when I tested it (timeouts and 503 "high demand" on both keys, plus slow hidden
  "thinking"), so it is not the default (set `LLM_MODEL=gemini-flash-latest` in `.env` to try it). The lighter `-lite` models answered in 1 to 5 seconds.
- **iMac is small.** With 12 pages the naive baseline can also answer well; the advanced pipeline's gain there shows
  mainly in ranking quality and in not depending on luck.
- **No scanned-PDF support.** All three documents have a text layer; image-only pages would need OCR.
- **Paths are hard-coded** to `C:\Users\Bacancy\Downloads` in `rag/common.py`.

## Project layout

```
rag/common.py            Chunk type, document registry, sentence packing
rag/layout.py            column order, header/footer removal, ligatures, word->row helpers
rag/ingest_narrative.py  use case 1 (+ naive baseline chunker)
rag/ingest_structured.py use case 2
rag/ingest_visual.py     use case 3
rag/store.py             ChromaDB + BM25 index
rag/router.py            query -> metadata constraints
rag/retrieve.py          hybrid retrieval, fusion, rerank, expansion
rag/answer.py            grounded prompt, citation cleanup, number verification
rag/llm.py               Gemini/Groq client: key rotation, model cooldowns, shared rate-limit pacing
eval/questions.py        questions, ground truth, expected pages
evaluate.py              metrics for naive vs advanced
make_report.py           writes the Results block of this file
api.py                   FastAPI service (also serves rag-ui/dist)
run_server.py            launcher for the app on :8100
rag-ui/                  React + TypeScript UI (Ask, Compare pipelines, How it works)
ui/index.html            plain HTML fallback page, used only if rag-ui/dist does not exist
```

API: `GET /api/docs`, `GET /api/models`, `GET /api/health`,
`POST /api/ask {question, doc: auto|gpo|gep|imac, mode: advanced|naive, model?}`,
`GET /api/page/{doc}/{page}` (page image for citations).
