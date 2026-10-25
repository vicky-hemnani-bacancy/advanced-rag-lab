# Demo video script: Advanced RAG over three document types

**Length:** about 11 minutes. **Format:** screen recording with voice-over (Windows Game Bar `Win+G`, or OBS).
**Audience:** engineers and team leads who know what an LLM is but not necessarily how RAG is built.
**One-line story:** *One recipe does not fit all documents. We built a different preparation for each of three document
shapes, one shared search-and-answer pipeline, and we measured it against a naive baseline.*

Each scene below has **SHOW** (what is on screen and what you click) and **SAY** (the narration). Times are targets.

---

## Before you record (checklist)

1. Start the app: `cd RagChallenge` then `.venv\Scripts\python run_server.py`. Open http://localhost:8100.
2. **Warm it up.** Ask one throwaway question first. The first question after a restart loads the models and takes about 10 s.
3. **Pace yourself.** Gemini's free tier allows about 10 requests per minute. A Compare click uses 2. Do not click through
   many questions in a row; narrate while each answer loads (5 to 8 s).
4. Keep the browser at 100% zoom, window about 1280 px wide. Close anything showing keys. **Never show `.env`.**
5. Open these in your editor, in tabs, for the implementation scenes:
   `rag/ingest_structured.py`, `rag/ingest_visual.py`, `rag/retrieve.py`, `rag/answer.py`, `rag/llm.py`, `eval/questions.py`.
6. Have the README results table and the architecture slide (Scene 7) ready.
7. If a request ever hangs: stop and restart the server with `run_server.py`, then redo that question.

### Questions to use, with the answers you should see

| # | Document | Question | Expected answer (verify on screen) | Page |
|---|---|---|---|---|
| A | GPO | How many depository libraries did GPO staff visit in FY 2018? | **166** (not 1,133, which is the total number of libraries) | 21, 4-5 |
| B | World Bank | What is the growth outlook for South Asia in this report? | Growth softens to **6.3 percent in 2026** | 96 |
| C | World Bank | What is the growth outlook for East Asia and Pacific in 2026? | **4.2 percent** (not the South Asia number) | 81 |
| D | World Bank | According to the executive summary, what are the main risks to the global outlook? | Downside risks: escalating hostilities, prolonged commodity disruptions | 19 |
| E | iMac | What is the total carbon footprint of the iMac, and how much comes from product use versus manufacturing? | **346 kg CO2e**; product use **45%**, production **50%** | 10 |
| F | iMac | Which power adapter was used when testing iMac against the ENERGY STAR requirements? | **143 W** (this is in a footnote) | 12 |
| G | iMac | What is the power consumption of iMac in sleep mode at 115V? | **0.57 W** (this is in a table) | 12 |
| H | World Bank, Compare tab | What does Chapter 3 say about sovereign debt in developing economies? | Naive: "could not find"; Advanced: a grounded Chapter 3 summary | 109-133 |

---

## Scene 1: The problem (0:00 to 0:50)

**SHOW:** Title slide, then the README table of three documents (or a slide with three document thumbnails).

**SAY:**
> "A language model doesn't know what's inside your PDFs. Ask it directly and it guesses. RAG fixes that: find the right
> passages first, then let the model answer only from those. It's an open-book exam, and the whole skill is opening the
> book to the right page.
>
> Here we have three documents with three different shapes. A plain-text annual report. A 200-page World Bank report with
> chapters, regions and tables. And a 12-page Apple environmental report where the facts hide in charts, tables and
> footnotes. The lesson of this project is that you can't treat them the same way."

---

## Scene 2: Live demo, the plain-text report (0:50 to 2:15)

**SHOW:** App, **Ask** tab. Click the **GPO report** chip. Pipeline: **Advanced**. Ask **question A**.

**SAY (while it loads):**
> "I'll pick the GPO annual report and ask how many depository libraries staff visited. There's a trap in this document: it
> also says 1,133 libraries participate in the program overall. A weak system grabs the wrong number."

**SHOW (answer appears):** Point at the answer, the **S1 / S2** chips, the **numbers verified** badge, the model badge.

**SAY:**
> "166, with citations. Two things to notice. Every fact is tagged to a source. And this green badge means every number in
> the answer was found in the passages it cited. If the model had invented a number, it would turn red."

**SHOW:** Click the **S1** chip (scrolls to the source), then **view page**. The PDF page opens. Press `Esc` to close.

**SAY:**
> "I can click a citation, jump to the exact passage, and open the original PDF page. That's how you trust an answer."

---

## Scene 3: Live demo, the 200-page report (2:15 to 4:00)

**SHOW:** Click the **World Bank GEP** chip. Ask **question B** (South Asia).

**SAY (while it loads):**
> "The World Bank report has six regional sections that all talk about growth forecasts. The risk is mixing them up."

**SHOW (answer):** Point at the source cards: section path **Chapter 2: Regional Outlooks > South Asia > Outlook**.

**SAY:**
> "6.3 percent in 2026. And look at where the sources came from: Chapter 2, South Asia, Outlook. Each passage knows which
> chapter, region and section it belongs to."

**SHOW:** Ask **question C** (East Asia and Pacific).

**SAY:**
> "Now East Asia: 4.2 percent. Same kind of question, different region, different answer, no leakage between them."

**SHOW:** Ask **question D** (executive summary risks). Point at **p. 19** in the sources.

**SAY:**
> "And if I say 'according to the executive summary', the system searches the executive summary. The same text also appears in
> Chapter 1, but the question asks for the summary, so that's where the answer comes from."

---

## Scene 4: Live demo, charts, tables and footnotes (4:00 to 5:30)

**SHOW:** Click the **iMac report** chip. Ask **question E**.

**SAY:**
> "The Apple report is where plain text extraction falls apart. This question needs a chart total, 346 kilograms, and a table
> split, 45 percent product use, 50 percent production."

**SHOW (answer):** Point at the **table** badge on the first source. Open **view page** on that source (page 10).

**SAY:**
> "The answer came from a table on page 10."

**SHOW:** Ask **question G** (sleep mode 115V), then **question F** (power adapter).

**SAY:**
> "0.57 watts, from a table. I'll come back to why that's harder than it looks. And this one, which power adapter was used in
> testing, is answered by a footnote at the back of the document, 143 watts. The system links each footnote to the claim it
> explains."

---

## Scene 5: Naive versus advanced, side by side (5:30 to 6:45)

**SHOW:** Click the **Compare pipelines** tab. Click the **World Bank GEP** chip, then click the sample question
**"What does Chapter 3 say about sovereign debt in developing economies?"** (question H).

**SAY (while both load):**
> "This tab sends the same question to two pipelines. On the left, the naive baseline: text cut into fixed 1,000-character
> pieces, vector search only, no checks. On the right, the advanced pipeline."

**SHOW (both answers):** Naive says it could not find the answer; advanced gives a Chapter 3 summary. Show the page numbers in the sources.

**SAY:**
> "The naive version pulls back fragments from Chapter 3 that don't actually contain the answer and, to its credit, says it
> can't find it. The advanced version retrieves the chapter's introduction and main findings, and answers from them. With a different model the naive version can fail in a worse way: in an
> earlier run it confidently said the govinfo system was fully deployed in December 2017, which is actually when the beta
> ended."

---

## Scene 6: How it works, the big picture (6:45 to 8:15)

**SHOW:** Architecture slide (draw or use this):

```
PREPARE ONCE          PDF -> parse layout -> chunk (per document type) -> embed -> ChromaDB + BM25
EVERY QUESTION        question -> router -> meaning search + keyword search -> fuse -> rerank -> top 6
                      -> Gemini answers from sources only -> check numbers -> answer with citations
```

**SAY:**
> "Two phases. First, we prepare each document once. We read the PDF with its layout, cut it into pieces of about 200 words
> that each keep their page and section, turn each piece into a vector of numbers that captures its meaning, and store them
> in a vector database, plus a keyword index.
>
> Then for every question: we search two ways, by meaning and by exact keywords, because each catches what the other misses.
> We merge the two lists. A second, smarter model, a cross-encoder, reads the question with each of the top twenty passages
> and keeps the best six. Gemini gets only those six, with strict rules: cite every fact, quote numbers exactly, never invent
> figures, or say it can't find the answer. Finally we check that every number in the answer appears in the cited sources."

**SHOW (optional, in the editor):** `rag/retrieve.py` (the fusion and rerank), then `rag/answer.py` (the system prompt and the number check).

**SAY (one sentence of detail):**
> "Embeddings and reranking run locally on CPU. Only the answer step calls Gemini."

---

## Scene 7: How it works, one design per document (8:15 to 9:50)

**SHOW:** Click **How it works** in the app and switch between the three document chips as you speak. Cut to the editor where noted.

**SAY, GPO:**
> "For the plain-text report the work is mostly cleaning. Pages have columns and captions, so we put text blocks into reading
> order and remove repeated headers. We cut on sentence boundaries so a fact is never split in half."

**SAY, World Bank (cut to `rag/ingest_structured.py`, the heading state machine):**
> "For the long report, structure is everything. We read font family and size to detect chapters, regions, boxes and
> sections, and tag every chunk with where it lives. The PDF's own bookmarks were off by one page, so we couldn't trust them.
> At question time, 'South Asia' or 'Chapter 3' becomes a filter, so the right section is searched. Tables are rebuilt from
> word positions so numbers inside them are searchable."

**SAY, iMac (cut to `rag/ingest_visual.py`, the table and footnote code):**
> "For the Apple report we wrote a separate extractor for each kind of content. The built-in table extractor turned 0.27 watts
> into 027, dropping the decimal point, so we use it only to find the cells and re-read the text ourselves. Footnotes are
> parsed and attached to the sentences that cite them. Icon call-outs get their own chunks. And a vision model reads the
> charts, but every number it returns is checked against the PDF's real text, because vision models do misread."

---

## Scene 8: Does it actually work? The evaluation (9:50 to 10:35)

**SHOW:** The results slide (or the results table in the README). Point at the "answer correct" and "right page ranked #1" rows.

**SAY:**
> "We wrote 27 questions with verified answers, including three out-of-scope ones that should get 'not found'. On the 24
> answerable ones, the naive pipeline got 88 percent right, with the right page first only 58 percent of the time. The
> advanced pipeline got all 24, with the right page first 96 percent of the time. All out-of-scope questions were refused
> by both, and no answer contained a number missing from its sources.
>
> Now the honest part. I tuned the pipeline while looking at these same questions, so this is a development result, not an
> unbiased benchmark. The set is small. And the model matters: the README states which model wrote these answers.
> With a different model the naive baseline scored lower."

---

## Scene 9: What broke, and what we learned (10:35 to 11:20)

**SHOW:** Slide with four bullets (or the README "What went wrong" section).

**SAY:**
> "Most of the real progress came from looking at the data, not from tuning. The World Bank text had lost the 'h' in every
> 'Th' word, 'Te global economy', 318 times. Table text lost its decimal points. The vision model misread a footnote number
> and described the same icon on six pages, so we now verify and filter it. And several of my 'failures' were bugs in my own
> test, such as an answer check that wanted the exact phrase 'interest rate' when the answer said 'bond yields'. I fixed
> the test, not the system."

---

## Scene 10: Limitations and close (11:20 to 12:00)

**SHOW:** Slide: limitations on the left, next steps on the right.

**SAY:**
> "What it can't do yet. The router that maps 'South Asia' to a section is rule-based and specific to this one report, so a
> new long document needs new rules or an LLM router. The 'not found' score threshold was set for an earlier reranker and
> needs recalibrating. Free API quotas limit heavy use. And we have no OCR for scanned pages.
>
> What I'd do next: a held-out question set, an LLM-based router, and a paid model tier or a local model for sustained use.
>
> The code, the README and the evaluation are all in the project folder. Thanks for watching."

---

## Slide text (copy into slides)

1. **Title:** Advanced RAG: one recipe does not fit every document
2. **Three documents:** plain text (82 pp) / structured report (200 pp) / charts, tables, footnotes (12 pp)
3. **Pipeline:** the architecture diagram from Scene 6
4. **Per-document design:** three columns: parse, chunk, search, with one line each
5. **Results:** naive 88% correct, 58% right page first; advanced 100% correct, 96% right page first (24 questions, Gemini flash-lite)
6. **What broke:** lost "Th" letters (318), lost decimal points, vision misreads, my own test bugs
7. **Limitations and next steps**

## Numbers you can quote (all from the project)

- Chunks indexed: GPO 124, World Bank 425, iMac 44.
- Models: `bge-base-en-v1.5` embeddings (768 numbers per chunk), `jina-reranker-v1-turbo-en` reranker, Gemini `gemini-flash-lite-latest` for answers.
- Search: top 40 by meaning plus top 40 by keyword, merged, top 20 reranked, best 6 sent to the model.
- Evaluation: 27 questions, 24 answerable. Median time per question: naive 4 s, advanced 7 s.

## Say this, not that

| Don't say | Say instead |
|---|---|
| "It never hallucinates." | "Every number is checked against its sources, and it refuses when it can't find the answer." |
| "100% accurate." | "It answered all 24 test questions correctly, but I tuned it on those questions." |
| "Production ready." | "A working prototype with a clear list of limitations." |
| "The naive version is bad." | "The naive version is a fair first attempt; here is where it breaks." |

## Likely questions from viewers

- **Why not just send the whole PDF to the model?** The 200-page report is far too long for reliable answers and cost; retrieval also gives citations you can check.
- **Why two searches?** Meaning search finds paraphrases; keyword search finds exact terms like "FDsys" or "6.3".
- **Why rerank?** The first search is fast but rough; a cross-encoder reads question and passage together and orders them better.
- **Why Gemini flash-lite and not the bigger model?** `gemini-flash-latest` was timing out when tested; the lite model answers in 1 to 5 seconds and passed the evaluation. The model is a one-line setting in `.env` (`LLM_MODEL`).
- **Can it handle a new document?** The shared pipeline can. Each new document shape may need its own parsing; that is the project's main point.
