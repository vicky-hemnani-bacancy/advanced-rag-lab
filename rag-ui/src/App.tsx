import { useEffect, useState } from 'react'
import { api } from './api'
import type { DocInfo, ModelsInfo, Source } from './api'
import AskView from './components/AskView'
import CompareView from './components/CompareView'
import HowItWorks from './components/HowItWorks'
import PageModal from './components/PageModal'

type Tab = 'ask' | 'compare' | 'how'
const TABS: { key: Tab; label: string }[] = [
  { key: 'ask', label: 'Ask' },
  { key: 'compare', label: 'Compare pipelines' },
  { key: 'how', label: 'How it works' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('ask')
  const [docs, setDocs] = useState<DocInfo[]>([])
  const [models, setModels] = useState<ModelsInfo | null>(null)
  const [online, setOnline] = useState<boolean | null>(null)
  const [viewer, setViewer] = useState<{ doc: string; page: number } | null>(null)

  useEffect(() => {
    let alive = true
    const load = () => {
      Promise.all([api.docs(), api.models()])
        .then(([d, m]) => { if (alive) { setDocs(d); setModels(m); setOnline(true) } })
        .catch(() => { if (alive) { setOnline(false); window.setTimeout(load, 4000) } })
    }
    load()
    return () => { alive = false }
  }, [])

  const pagesOf = (doc: string) => docs.find((d) => d.key === doc)?.pages ?? 999
  const onViewPage = (s: Source) => setViewer({ doc: s.doc, page: s.page })

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">R</span>
          <div>
            <b>Advanced RAG Lab</b>
            <small>three documents · three pipelines{models ? ` · ${models.provider}` : ''}</small>
          </div>
        </div>
        <nav className="tabs" aria-label="Sections">
          {TABS.map((t) => (
            <button key={t.key} className={tab === t.key ? 'active' : ''} onClick={() => setTab(t.key)}>{t.label}</button>
          ))}
        </nav>
        <span className={`status ${online ? 'on' : online === false ? 'off' : ''}`}>
          {online ? 'server online' : online === false ? 'server offline, retrying…' : 'connecting…'}
        </span>
      </header>

      <main>
        {online === false && (
          <div className="notice bad">
            The RAG server is not reachable. Start it with <code>.venv\Scripts\python run_server.py</code> (port 8100).
          </div>
        )}
        {tab === 'ask' && <AskView docs={docs} onViewPage={onViewPage} />}
        {tab === 'compare' && <CompareView docs={docs} onViewPage={onViewPage} />}
        {tab === 'how' && <HowItWorks />}
      </main>

      {viewer && (
        <PageModal doc={viewer.doc} page={viewer.page} totalPages={pagesOf(viewer.doc)} onClose={() => setViewer(null)} />
      )}
    </div>
  )
}
