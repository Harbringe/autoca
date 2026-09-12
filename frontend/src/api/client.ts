// One place that talks to the server.
//
// Authentication is the session cookie, so every request goes with
// credentials and every mutating one carries the CSRF token Django set. There
// is no token in JavaScript to steal.
//
// Errors are the API's own shape -- { code, detail, fields? } -- surfaced as
// an ApiError so a screen can show the server's sentence rather than invent
// one. The parser's messages name the row and the figure that broke; they are
// worth showing verbatim.

import type { Job } from './types'

export interface ApiErrorBody {
  code: string
  detail: string
  fields?: Record<string, string[]>
  verify_at?: string
}

export class ApiError extends Error {
  status: number
  code: string
  fields: Record<string, string[]>
  body: ApiErrorBody

  constructor(status: number, body: ApiErrorBody) {
    super(body.detail || `HTTP ${status}`)
    this.status = status
    this.code = body.code || 'error'
    this.fields = body.fields || {}
    this.body = body
  }

  fieldError(name: string): string | undefined {
    return this.fields[name]?.[0]
  }
}

type Listener = (error: ApiError) => void
const authListeners = new Set<Listener>()

/** Called for every 401/403 that means "not signed in" or "MFA needed". */
export function onAuthFailure(listener: Listener): () => void {
  authListeners.add(listener)
  return () => authListeners.delete(listener)
}

function readCookie(name: string): string {
  const match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'))
  return match ? decodeURIComponent(match[1]) : ''
}

let csrfReady: Promise<void> | null = null

async function ensureCsrf(): Promise<string> {
  if (!readCookie('csrftoken')) {
    csrfReady ??= fetch('/auth/csrf/', { credentials: 'same-origin' }).then(() => undefined)
    await csrfReady
  }
  return readCookie('csrftoken')
}

async function parse(response: Response): Promise<unknown> {
  const text = await response.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return { code: 'not_json', detail: text.slice(0, 200) }
  }
}

async function request<T>(method: string, url: string, body?: unknown, raw = false): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const init: RequestInit = { method, credentials: 'same-origin', headers }

  if (method !== 'GET' && method !== 'HEAD') {
    headers['X-CSRFToken'] = await ensureCsrf()
    if (body instanceof FormData) {
      init.body = body
    } else if (body !== undefined) {
      headers['Content-Type'] = 'application/json'
      init.body = JSON.stringify(body)
    }
  }

  const response = await fetch(url, init)
  const data = (await parse(response)) as T | ApiErrorBody | null

  if (!response.ok) {
    const error = new ApiError(response.status, (data as ApiErrorBody) || { code: 'error', detail: response.statusText })
    if (
      response.status === 401 ||
      (response.status === 403 &&
        ['mfa_required', 'mfa_enrolment_required', 'not_authenticated'].includes(error.code))
    ) {
      authListeners.forEach((listener) => listener(error))
    }
    throw error
  }
  return (raw ? data : data) as T
}

export const api = {
  get: <T>(url: string) => request<T>('GET', url),
  post: <T>(url: string, body?: unknown) => request<T>('POST', url, body),
  patch: <T>(url: string, body?: unknown) => request<T>('PATCH', url, body),
  put: <T>(url: string, body?: unknown) => request<T>('PUT', url, body),
  delete: <T>(url: string) => request<T>('DELETE', url),
}

export const V1 = '/api/v1'

/** Poll a job until it is finished. Work runs inline today, so this usually returns at once. */
export async function waitForJob(job: Job, onUpdate?: (job: Job) => void): Promise<Job> {
  let current = job
  let delay = 500
  while (current.status === 'PENDING' || current.status === 'RUNNING') {
    await new Promise((resolve) => setTimeout(resolve, delay))
    current = await api.get<Job>(`${V1}/jobs/${current.id}/`)
    onUpdate?.(current)
    delay = Math.min(delay * 1.5, 3000)
  }
  return current
}

/** Fetch every page of a paginated collection. Fine at this product's volumes. */
export async function allPages<T>(url: string): Promise<T[]> {
  const out: T[] = []
  let next: string | null = url.includes('?') ? `${url}&page_size=500` : `${url}?page_size=500`
  while (next) {
    const page: { results: T[]; next: string | null } = await api.get(next)
    out.push(...page.results)
    next = page.next ? page.next.replace(/^https?:\/\/[^/]+/, '') : null
  }
  return out
}
