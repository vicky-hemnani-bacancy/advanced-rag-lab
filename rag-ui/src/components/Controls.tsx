import type { DocInfo, DocKey, Mode } from '../api'

interface Props {
  docs: DocInfo[]
  doc: DocKey
  onDoc: (d: DocKey) => void
  mode?: Mode
  onMode?: (m: Mode) => void
}

const SHORT: Record<string, string> = { gpo: 'GPO report', gep: 'World Bank GEP', imac: 'iMac report' }
const HINT: Record<string, string> = {
  gpo: 'Narrative text', gep: '200-page structured report', imac: 'Charts, tables, footnotes',
}

export default function Controls({ docs, doc, onDoc, mode, onMode }: Props) {
  return (
    <div className="controls">
      <div className="control-group">
        <label>Document</label>
        <div className="chips">
          <button className={`chip ${doc === 'auto' ? 'active' : ''}`} onClick={() => onDoc('auto')}>
            Auto<small>search all three</small>
          </button>
          {docs.map((d) => (
            <button key={d.key} className={`chip ${doc === d.key ? 'active' : ''}`} onClick={() => onDoc(d.key)}
                    title={d.desc}>
              {SHORT[d.key] ?? d.title}<small>{HINT[d.key]} · {d.pages} pp</small>
            </button>
          ))}
        </div>
      </div>

      {mode && onMode && (
        <div className="control-group">
          <label>Pipeline</label>
          <div className="segmented">
            <button className={mode === 'advanced' ? 'active' : ''} onClick={() => onMode('advanced')}
                    title="Layout-aware parsing, hybrid search, reranking, grounded answer with verification">Advanced</button>
            <button className={mode === 'naive' ? 'active' : ''} onClick={() => onMode('naive')}
                    title="Fixed 1000-character chunks, vector search only, no checks">Naive baseline</button>
          </div>
        </div>
      )}
    </div>
  )
}
