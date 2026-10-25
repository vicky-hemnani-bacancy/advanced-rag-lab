export type DocKey = 'auto' | 'gpo' | 'gep' | 'imac'
export type Mode = 'advanced' | 'naive'

export interface DocInfo {
  key: Exclude<DocKey, 'auto'>
  title: string
  desc: string
  pages: number
  samples: string[]
}

export interface Source {
  tag: string
  doc: Exclude<DocKey, 'auto'>
  page: number
  page_end: number
  section: string
  kind: string
  score: number
  why: string
  text: string
}

export interface AskResult {
  answer: string
  abstained: boolean
  cited: number[]
  ungrounded_numbers: string[]
  routing: string
  timings: Record<string, number>
  sources: Source[]
  mode: Mode
  model: string
}

export interface ModelsInfo {
  provider: string
  default: string
  models: string[]
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(url, init)
  } catch {
    throw new ApiError('Cannot reach the RAG server. Is it running on port 8100?', 0)
  }
  if (!res.ok) {
    let msg = res.statusText
    try {
      const body = await res.json()
      msg = body.detail ?? msg
    } catch {
      msg = (await res.text().catch(() => '')).slice(0, 200) || msg
    }
    throw new ApiError(typeof msg === 'string' ? msg : JSON.stringify(msg), res.status)
  }
  return res.json() as Promise<T>
}

export const api = {
  docs: () => request<DocInfo[]>('/api/docs'),
  models: () => request<ModelsInfo>('/api/models'),
  ask: (body: { question: string; doc: DocKey; mode: Mode; model?: string }, signal?: AbortSignal) =>
    request<AskResult>('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    }),
  pageUrl: (doc: string, page: number, dpi = 100) => `/api/page/${doc}/${page}?dpi=${dpi}`,
}

export function loadPref<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem('rag:' + key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

export function savePref(key: string, value: unknown) {
  try {
    localStorage.setItem('rag:' + key, JSON.stringify(value))
  } catch {
    // storage unavailable (private mode): preferences just won't persist
  }
}
