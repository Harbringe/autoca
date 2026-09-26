// The one place that talks to the server.
//
// Authentication is the session cookie, so nothing here holds a credential. A
// mutating request carries Django's CSRF token; the token is fetched as JSON
// and kept in memory rather than read back out of the cookie, which is what
// lets the same code run where the webview cannot see the server's cookies.
//
// A non-2xx answer is thrown as an ApiError, so a query or a mutation fails the
// way TanStack Query expects and no screen has to remember to check a status.

import createClient from 'openapi-fetch'
import { API_BASE } from '@/platform/env'
import { send } from '@/platform/http'
import { ApiError, SESSION_CODES, type ApiErrorBody } from './errors'
import type { paths } from './schema'

const SAFE = new Set(['GET', 'HEAD', 'OPTIONS'])

// --- CSRF -------------------------------------------------------------------

let csrfToken: string | null = null
let csrfInFlight: Promise<string> | null = null

async function loadCsrf(): Promise<string> {
  const response = await send(new Request(`${API_BASE}/auth/csrf/`, { credentials: 'include' }))
  if (!response.ok) throw new ApiError(response.status, { detail: 'Could not start a secure session.' })
  const body = (await response.json()) as { csrfToken: string }
  return body.csrfToken
}

export async function ensureCsrf(): Promise<string> {
  if (csrfToken) return csrfToken
  csrfInFlight ??= loadCsrf()
    .then((token) => (csrfToken = token))
    .finally(() => (csrfInFlight = null))
  return csrfInFlight
}

/** Django rotates the token when the session changes, so sign-in and sign-out must call this. */
export function resetCsrf(): void {
  csrfToken = null
}

// --- session events ---------------------------------------------------------

type SessionListener = (error: ApiError) => void
const sessionListeners = new Set<SessionListener>()

/** Told when any request finds the session signed out, or short of its second factor. */
export function onSessionChange(listener: SessionListener): () => void {
  sessionListeners.add(listener)
  return () => sessionListeners.delete(listener)
}

// --- transport --------------------------------------------------------------

async function errorFrom(response: Response): Promise<ApiError> {
  const text = await response.text()
  let body: Partial<ApiErrorBody> = {}
  try {
    body = JSON.parse(text) as Partial<ApiErrorBody>
  } catch {
    body = { code: 'not_json', detail: `The server answered ${response.status}.` }
  }
  const retry = Number(response.headers.get('Retry-After'))
  return new ApiError(response.status, body, Number.isFinite(retry) && retry > 0 ? retry : null)
}

async function looksLikeCsrfFailure(response: Response): Promise<boolean> {
  if (response.status !== 403) return false
  const text = await response.clone().text()
  return /csrf/i.test(text)
}

/** Every request, from the generated client and from the hand-typed helpers, goes through here. */
export async function apiFetch(request: Request): Promise<Response> {
  const mutating = !SAFE.has(request.method.toUpperCase())
  const spare = mutating ? request.clone() : null

  if (mutating) request.headers.set('X-CSRFToken', await ensureCsrf())
  let response = await send(request)

  if (mutating && spare && (await looksLikeCsrfFailure(response))) {
    // The token went stale (a sign-in elsewhere rotated it). Ask for a fresh one, once.
    resetCsrf()
    spare.headers.set('X-CSRFToken', await ensureCsrf())
    response = await send(spare)
  }

  if (!response.ok) {
    const error = await errorFrom(response)
    if (SESSION_CODES.has(error.code)) sessionListeners.forEach((listener) => listener(error))
    throw error
  }
  return response
}

/** The typed client: paths and bodies come from the backend's OpenAPI schema. */
export const api = createClient<paths>({
  baseUrl: API_BASE,
  fetch: apiFetch,
  credentials: 'include',
})

// --- hand-typed endpoints ---------------------------------------------------
//
// Team, firm, audit and the /auth/* endpoints are plain Django views, so the
// schema has nothing to say about their shapes (see src/api/types.ts). They go
// through the same transport, with the response type stated at the call site.

type Query = Record<string, string | number | boolean | null | undefined>

function url(path: string, query?: Query): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const qs = search.toString()
  return `${API_BASE}${path}${qs ? `?${qs}` : ''}`
}

async function json<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T
  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}

function withBody(method: string, path: string, body?: unknown): Request {
  const headers = new Headers({ Accept: 'application/json' })
  let payload: BodyInit | undefined
  if (body instanceof FormData) {
    payload = body
  } else if (body !== undefined) {
    headers.set('Content-Type', 'application/json')
    payload = JSON.stringify(body)
  }
  return new Request(url(path), { method, headers, body: payload, credentials: 'include' })
}

export const raw = {
  get: async <T>(path: string, query?: Query) =>
    json<T>(await apiFetch(new Request(url(path, query), { headers: { Accept: 'application/json' }, credentials: 'include' }))),
  post: async <T>(path: string, body?: unknown) => json<T>(await apiFetch(withBody('POST', path, body))),
  put: async <T>(path: string, body?: unknown) => json<T>(await apiFetch(withBody('PUT', path, body))),
  patch: async <T>(path: string, body?: unknown) => json<T>(await apiFetch(withBody('PATCH', path, body))),
  delete: async <T = void>(path: string) => json<T>(await apiFetch(withBody('DELETE', path))),
  /** A file the server sends back: the GST working paper, for one. */
  blob: async (path: string, query?: Query) => {
    const response = await apiFetch(new Request(url(path, query), { credentials: 'include' }))
    const disposition = response.headers.get('Content-Disposition') ?? ''
    const name = /filename="?([^";]+)"?/.exec(disposition)?.[1]
    return { blob: await response.blob(), filename: name }
  },
}

/** Unwraps a generated-client call whose failures have already been thrown. */
export function data<T>(result: { data?: T }): T {
  return result.data as T
}
