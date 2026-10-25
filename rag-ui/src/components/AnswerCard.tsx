import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { AskResult, Source } from '../api'

interface Props {
  result: AskResult
  title?: string
  onViewPage: (s: Source) => void
}

const KIND_LABEL: Record<string, string> = {
  text: 'text', table: 'table', chart: 'chart (vision)', callout: 'call-out', footnote: 'footnote',
}

export default function AnswerCard({ result, title, onViewPage }: Props) {
  const [open, setOpen] = useState<number | null>(null)
  const [flash, setFlash] = useState<number | null>(null)
  const notFound = result.abstained || /could not find this in the document/i.test(result.answer)

  // [S1] -> markdown link, rendered below as a clickable chip
  const md = result.answer.replace(/\[S(\d+)\]/g, (_, n) => `[S${n}](#cite-${n})`)

  function jumpTo(n: number) {
    setOpen(n - 1)
    setFlash(n)
    window.setTimeout(() => setFlash(null), 1400)
    document.getElementById(`src-${result.mode}-${n}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }

  const t = result.timings
  return (
    <div className="card answer-card">
      {title && <div className="card-title">{title}</div>}
      <div className="badges">
        <span className={`badge ${result.mode === 'advanced' ? 'b-primary' : 'b-muted'}`}>{result.mode}</span>
        {notFound && <span className="badge b-warn">not found in document</span>}
        {!notFound && result.mode === 'advanced' && (
          result.ungrounded_numbers.length > 0
            ? <span className="badge b-bad" title="These numbers do not appear in the cited sources">
                unverified numbers: {result.ungrounded_numbers.join(', ')}
              </span>
            : <span className="badge b-ok" title="Every number in the answer appears in its cited sources">numbers verified</span>
        )}
        {result.model && <span className="badge b-muted">{result.model}</span>}
      </div>

      <div className="answer">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children }) => {
              const m = href?.match(/^#cite-(\d+)$/)
              if (m) {
                const n = Number(m[1])
                return <button className="cite" onClick={() => jumpTo(n)}>{children}</button>
              }
              return <a href={href} target="_blank" rel="noreferrer">{children}</a>
            },
          }}
        >
          {md}
        </ReactMarkdown>
      </div>

      <div className="meta">
        {result.routing && <span>Routing: {result.routing}</span>}
        <span>
          {Object.entries(t).filter(([k]) => k !== 'total').map(([k, v]) => `${k} ${v}s`).join(' · ')}
          {t.total != null && ` · total ${t.total}s`}
        </span>
      </div>

      <details className="sources" open={result.cited.length > 0 && !notFound}>
        <summary>Sources ({result.sources.length}){result.cited.length > 0 && ` · ${result.cited.length} cited`}</summary>
        {result.sources.map((s, i) => {
          const n = i + 1
          const cited = result.cited.includes(n)
          const isOpen = open === i
          return (
            <div
              key={s.tag + i}
              id={`src-${result.mode}-${n}`}
              className={`source ${cited ? 'cited' : ''} ${flash === n ? 'flash' : ''}`}
            >
              <div className="source-head" onClick={() => setOpen(isOpen ? null : i)}>
                <b>S{n}</b>
                <span className="badge b-muted">{KIND_LABEL[s.kind] ?? s.kind}</span>
                <span>{s.doc.toUpperCase()} · p.{s.page}{s.page_end !== s.page ? `–${s.page_end}` : ''}</span>
                {s.section && <span className="source-section">{s.section}</span>}
                <span className="score" title="reranker relevance score">{s.score.toFixed(1)}</span>
                {cited && <span className="badge b-ok">cited</span>}
                <button
                  className="link"
                  onClick={(e) => { e.stopPropagation(); onViewPage(s) }}
                >view page</button>
              </div>
              <pre className={isOpen ? 'open' : ''}>{s.text}</pre>
            </div>
          )
        })}
      </details>
    </div>
  )
}
