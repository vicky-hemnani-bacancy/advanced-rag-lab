import { useEffect, useState } from 'react'
import { api } from '../api'

interface Props {
  doc: string
  page: number
  totalPages: number
  onClose: () => void
}

export default function PageModal({ doc, page: initial, totalPages, onClose }: Props) {
  const [page, setPage] = useState(initial)
  const [zoom, setZoom] = useState(1)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => { setPage(initial) }, [initial])
  useEffect(() => { setLoaded(false) }, [page])

  const go = (d: number) => setPage((p) => Math.min(totalPages, Math.max(1, p + d)))

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowRight') go(1)
      if (e.key === 'ArrowLeft') go(-1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Source page">
        <div className="modal-bar">
          <b>{doc.toUpperCase()}</b>
          <button className="icon-btn" onClick={() => go(-1)} disabled={page <= 1} aria-label="Previous page">‹</button>
          <span>page {page} / {totalPages}</span>
          <button className="icon-btn" onClick={() => go(1)} disabled={page >= totalPages} aria-label="Next page">›</button>
          <span className="spacer" />
          <button className="icon-btn" onClick={() => setZoom((z) => Math.max(0.6, z - 0.2))} aria-label="Zoom out">−</button>
          <span>{Math.round(zoom * 100)}%</span>
          <button className="icon-btn" onClick={() => setZoom((z) => Math.min(2.4, z + 0.2))} aria-label="Zoom in">+</button>
          <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="modal-body">
          {!loaded && <div className="modal-loading">Loading page…</div>}
          <img
            src={api.pageUrl(doc, page, 110)}
            alt={`${doc} page ${page}`}
            style={{ width: `${zoom * 100}%`, display: loaded ? 'block' : 'none' }}
            onLoad={() => setLoaded(true)}
          />
        </div>
      </div>
    </div>
  )
}
