import { useState } from 'react'

interface Step { title: string; text: string }

const SHARED: Step[] = [
  { title: '1. Search two ways', text: 'Meaning search (bge-base embeddings in ChromaDB) and keyword search (BM25) run together. Each catches what the other misses. Results are merged with Reciprocal Rank Fusion.' },
  { title: '2. Re-rank', text: 'A cross-encoder reads the question together with each of the top 20 passages and scores how well each one actually answers it. The best 6 are kept.' },
  { title: '3. Answer from sources only', text: 'The LLM (Gemini) gets only those passages with strict rules: cite every fact as [S#], quote numbers exactly, never invent figures, or say “I could not find this in the document”.' },
  { title: '4. Check the answer', text: 'Every number in the answer must appear in the sources it cites; otherwise the answer is flagged. If nothing relevant is found, the system refuses instead of guessing.' },
]

const DOCS: Record<string, { name: string; problem: string; steps: Step[] }> = {
  gpo: {
    name: 'GPO report',
    problem: 'Plain narrative text. Facts sit inside sentences, and near-duplicate numbers act as distractors (166 libraries visited vs 1,133 in total; “$375 million” vs “$375.7 million”).',
    steps: [
      { title: 'Read the layout', text: 'Pages have columns and side captions. Blocks are put into reading order and running headers/footers are removed.' },
      { title: 'Cut on sentence boundaries', text: 'About 220 words per chunk with one sentence of overlap, so a fact is never split in half. Each chunk keeps its page range.' },
      { title: 'Why it matters', text: 'Without this, the naive pipeline said govinfo was “fully deployed in December 2017” (that was the end of the beta).' },
    ],
  },
  gep: {
    name: 'World Bank GEP',
    problem: '200 pages of chapters, regions, boxes and tables. The same topic appears in several places (executive summary, Chapter 1, regional sections).',
    steps: [
      { title: 'Detect the structure', text: 'Font family and size drive a heading state machine: chapter → section → sub-section, plus region and “Box” articles. PDF bookmarks were off by a page, so they are not used.' },
      { title: 'Chunk inside sections', text: 'Text is only packed within one section and every chunk carries its chapter, region and section path.' },
      { title: 'Route the query', text: '“South Asia”, “Chapter 3” or “executive summary” become metadata constraints, so the right section is searched and the wrong region cannot leak in.' },
      { title: 'Rebuild tables', text: 'Forecast tables are rebuilt from word positions with their year headers, so numbers in tables are searchable.' },
    ],
  },
  imac: {
    name: 'iMac report',
    problem: 'Short, but the facts live in charts, icon call-outs, tables and footnotes, not in paragraphs.',
    steps: [
      { title: 'Tables from geometry', text: 'The built-in extractor turned 0.27W into 027W. Cell positions give the structure and the text is re-read from the PDF, then stored as a grid plus “row facts”.' },
      { title: 'Link footnotes', text: '“58 percent less energy” is stored together with footnote 18, which explains how it was tested. Footnotes are also searchable on their own.' },
      { title: 'Call-outs', text: 'Short icon/stat blocks (“100 percent recycled aluminum in the stand”) get their own chunk for precise matching.' },
      { title: 'Read charts, then verify', text: 'A vision model reads chart pages, and every number it returns is checked against the PDF text. Charts are labelled machine-read so the answer prefers text and tables.' },
    ],
  },
}

export default function HowItWorks() {
  const [doc, setDoc] = useState('gpo')
  const d = DOCS[doc]
  return (
    <div className="view">
      <div className="empty left">
        <h2>How it works</h2>
        <p>Each document is a different shape, so each gets its own preparation. After that, all three share one search-and-answer pipeline.</p>
      </div>

      <div className="control-group">
        <label>Document-specific preparation</label>
        <div className="chips">
          {Object.entries(DOCS).map(([k, v]) => (
            <button key={k} className={`chip ${doc === k ? 'active' : ''}`} onClick={() => setDoc(k)}>{v.name}</button>
          ))}
        </div>
      </div>

      <div className="card">
        <p><b>The challenge:</b> {d.problem}</p>
        <div className="steps">
          {d.steps.map((s) => (
            <div key={s.title} className="step"><b>{s.title}</b><p>{s.text}</p></div>
          ))}
        </div>
      </div>

      <h3 className="section-title">Then, for every question</h3>
      <div className="steps">
        {SHARED.map((s) => (
          <div key={s.title} className="step card"><b>{s.title}</b><p>{s.text}</p></div>
        ))}
      </div>
    </div>
  )
}
