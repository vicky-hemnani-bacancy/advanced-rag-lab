import { useEffect, useState } from 'react'
import { api, ApiError, loadPref, savePref } from '../api'
import type { AskResult, DocInfo, DocKey, Mode, Source } from '../api'
import AnswerCard from './AnswerCard'
import Controls from './Controls'

interface Side {
  status: 'idle' | 'loading' | 'done' | 'error'
  result?: AskResult
  error?: string
}

interface Props {
  docs: DocInfo[]
  onViewPage: (s: Source) => void
}

export default function CompareView({ docs, onViewPage }: Props) {
  const [doc, setDoc] = useState<DocKey>(() => loadPref('cmp-doc', 'gep'))
  const [input, setInput] = useState('')
  const [asked, setAsked] = useState('')
  const [sides, setSides] = useState<Record<Mode, Side>>({ naive: { status: 'idle' }, advanced: { status: 'idle' } })

  useEffect(() => { savePref('cmp-doc', doc) }, [doc])

  async function runSide(mode: Mode, question: string) {
    setSides((s) => ({ ...s, [mode]: { status: 'loading' } }))
    try {
      const result = await api.ask({ question, doc, mode })
      setSides((s) => ({ ...s, [mode]: { status: 'done', result } }))
    } catch (e) {
      setSides((s) => ({ ...s, [mode]: { status: 'error', error: e instanceof ApiError ? e.message : String(e) } }))
    }
  }

  function submit(q: string) {
    const question = q.trim()
    if (!question) return
    setAsked(question)
    setInput(question)
    void runSide('naive', question)
    void runSide('advanced', question)
  }

  const samples = doc === 'auto' ? docs.flatMap((d) => d.samples.slice(0, 2)) : (docs.find((d) => d.key === doc)?.samples ?? [])

  return (
    <div className="view">
      <Controls docs={docs} doc={doc} onDoc={(d) => { setDoc(d); setAsked(''); setSides({ naive: { status: 'idle' }, advanced: { status: 'idle' } }) }} />

      <form className="composer" onSubmit={(e) => { e.preventDefault(); submit(input) }}>
        <input value={input} onChange={(e) => setInput(e.target.value)} aria-label="Question"
               placeholder="One question, two pipelines, side by side…" />
        <button className="btn" type="submit" disabled={!input.trim()}>Compare</button>
      </form>

      {!asked && (
        <div className="empty">
          <h2>Naive baseline vs advanced pipeline</h2>
          <p>The same question goes to both. The naive one cuts text into fixed 1,000-character pieces and uses vector search only;
            the advanced one uses layout-aware parsing, hybrid search, reranking and answer checks. The differences show up most on the
            long World Bank report.</p>
          <div className="sample-list">
            {samples.map((s) => (
              <button key={s} className="sample" onClick={() => submit(s)}>{s}</button>
            ))}
          </div>
        </div>
      )}

      {asked && (
        <>
          <div className="bubble-user">{asked}</div>
          <div className="compare-grid">
            {(['naive', 'advanced'] as Mode[]).map((m) => {
              const s = sides[m]
              return (
                <div key={m} className="compare-col">
                  <h3>{m === 'naive' ? 'Naive baseline' : 'Advanced pipeline'}</h3>
                  {s.status === 'loading' && <div className="card loading"><span className="spinner" /> Working…</div>}
                  {s.status === 'error' && (
                    <div className="card error">
                      <div>{s.error}</div>
                      <button className="btn small" onClick={() => void runSide(m, asked)}>Try again</button>
                    </div>
                  )}
                  {s.status === 'done' && s.result && <AnswerCard result={s.result} onViewPage={onViewPage} />}
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
