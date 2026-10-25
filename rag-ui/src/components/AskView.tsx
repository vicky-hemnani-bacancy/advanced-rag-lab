import { useEffect, useRef, useState } from 'react'
import { api, ApiError, loadPref, savePref } from '../api'
import type { AskResult, DocInfo, DocKey, Mode, Source } from '../api'
import AnswerCard from './AnswerCard'
import Controls from './Controls'

interface Turn {
  id: number
  question: string
  doc: DocKey
  mode: Mode
  status: 'loading' | 'done' | 'error'
  result?: AskResult
  error?: string
  busy?: boolean
}

interface Props {
  docs: DocInfo[]
  onViewPage: (s: Source) => void
}

let nextId = 1

export default function AskView({ docs, onViewPage }: Props) {
  const [doc, setDoc] = useState<DocKey>(() => loadPref('doc', 'auto'))
  const [mode, setMode] = useState<Mode>(() => loadPref('mode', 'advanced'))
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const aborts = useRef(new Map<number, AbortController>())
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => { savePref('doc', doc) }, [doc])
  useEffect(() => { savePref('mode', mode) }, [mode])
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [turns.length])

  const samples = doc === 'auto' ? docs.flatMap((d) => d.samples.slice(0, 2)) : (docs.find((d) => d.key === doc)?.samples ?? [])

  async function run(id: number, question: string, d: DocKey, m: Mode) {
    const ctl = new AbortController()
    aborts.current.set(id, ctl)
    setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, status: 'loading', error: undefined } : t)))
    try {
      const result = await api.ask({ question, doc: d, mode: m }, ctl.signal)
      setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, status: 'done', result } : t)))
    } catch (e) {
      if ((e as Error).name === 'AbortError') {
        setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, status: 'error', error: 'Stopped.' } : t)))
        return
      }
      const msg = e instanceof ApiError ? e.message : String(e)
      setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, status: 'error', error: msg } : t)))
    } finally {
      aborts.current.delete(id)
    }
  }

  function submit(q: string) {
    const question = q.trim()
    if (!question) return
    const id = nextId++
    setTurns((ts) => [...ts, { id, question, doc, mode, status: 'loading' }])
    setInput('')
    void run(id, question, doc, mode)
  }

  const anyLoading = turns.some((t) => t.status === 'loading')

  return (
    <div className="view">
      <Controls docs={docs} doc={doc} onDoc={setDoc} mode={mode} onMode={setMode} />

      <div className="thread">
        {turns.length === 0 && (
          <div className="empty">
            <h2>Ask a question about the documents</h2>
            <p>Answers cite their sources. Click a citation chip to jump to the passage, or “view page” to see the original PDF page.</p>
            <div className="sample-list">
              {samples.map((s) => (
                <button key={s} className="sample" onClick={() => submit(s)}>{s}</button>
              ))}
            </div>
          </div>
        )}

        {turns.map((t) => (
          <div key={t.id} className="turn">
            <div className="bubble-user">
              {t.question}
              <small>{t.doc === 'auto' ? 'all documents' : t.doc} · {t.mode}</small>
            </div>
            {t.status === 'loading' && (
              <div className="card loading">
                <span className="spinner" /> Searching, reranking and writing the answer…
                <button className="link" onClick={() => aborts.current.get(t.id)?.abort()}>stop</button>
              </div>
            )}
            {t.status === 'error' && (
              <div className="card error">
                <div>{t.error}</div>
                <button className="btn small" onClick={() => void run(t.id, t.question, t.doc, t.mode)}>Try again</button>
              </div>
            )}
            {t.status === 'done' && t.result && <AnswerCard result={t.result} onViewPage={onViewPage} />}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <form className="composer" onSubmit={(e) => { e.preventDefault(); submit(input) }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={doc === 'auto' ? 'Ask anything about the three documents…' : `Ask about the ${doc.toUpperCase()} document…`}
          aria-label="Question"
          autoFocus
        />
        <button className="btn" type="submit" disabled={!input.trim()}>
          {anyLoading ? 'Queue' : 'Ask'}
        </button>
        {turns.length > 0 && (
          <button className="btn ghost" type="button" onClick={() => setTurns([])}>Clear</button>
        )}
      </form>
    </div>
  )
}
