// Talk to the AutoCA API the way the web app does, as one of the QA people, and keep a record.
//
// Sign-in follows the order the server needs: fetch a CSRF token, log in, fetch the token
// AGAIN (logging in rotates it), then send it on every write. Nothing here throws on a
// non-2xx answer: a refusal is data for a reviewer, so each call returns
// { status, ok, body, headers } and every call is appended to `session.calls`.
//
// Paths may be written with or without the leading slash (Git Bash on Windows rewrites an
// argument that starts with "/", so a path passed on a command line loses its meaning).

import { request } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { basename } from 'node:path'
import { PASSWORD, PEOPLE } from './session.mjs'

export const API = process.env.QA_API ?? 'http://127.0.0.1:8000'
const slash = (p) => (p.startsWith('/') ? p : `/${p}`)

export async function login(role = 'admin') {
  const ctx = await request.newContext({ baseURL: API })
  const calls = []
  let token = ''

  const csrf = async () => {
    token = (await (await ctx.get('/auth/csrf/')).json()).csrfToken
  }

  async function call(method, path, { data, multipart, query } = {}) {
    const url = slash(path)
    const headers = method === 'GET' ? {} : { 'X-CSRFToken': token }
    const response = await ctx.fetch(url, { method, headers, data, multipart, params: query })
    const text = await response.text()
    let body = text
    try {
      body = text ? JSON.parse(text) : null
    } catch {
      /* not JSON: a file, or an HTML error page */
    }
    const result = { status: response.status(), ok: response.ok(), body, headers: response.headers(), text }
    calls.push({ role, method, path: url, status: result.status })
    return result
  }

  await csrf()
  const signedIn = await call('POST', '/auth/login/', { data: { email: PEOPLE[role], password: PASSWORD } })
  if (!signedIn.ok) throw new Error(`could not sign in as ${role}: ${signedIn.status} ${JSON.stringify(signedIn.body)}`)
  await csrf()

  const session = {
    role,
    calls,
    get: (path, query) => call('GET', path, { query }),
    post: (path, data) => call('POST', path, { data: data ?? {} }),
    patch: (path, data) => call('PATCH', path, { data }),
    put: (path, data) => call('PUT', path, { data }),
    del: (path) => call('DELETE', path),
    /** Multipart upload of a local file. `fields` are extra form fields (strings). */
    upload: (path, filePath, fields = {}, { mimeType = 'application/pdf', name } = {}) =>
      call('POST', path, {
        multipart: { ...fields, file: { name: name ?? basename(filePath), mimeType, buffer: readFileSync(filePath) } },
      }),
    /** Upload bytes you made up (an empty file, a text file) rather than a file on disk. */
    uploadBytes: (path, buffer, name, mimeType, fields = {}) =>
      call('POST', path, { multipart: { ...fields, file: { name, mimeType, buffer } } }),
    /** Every page of a paginated list, as one array. */
    async all(path, query = {}) {
      const rows = []
      let page = 1
      for (;;) {
        const r = await call('GET', path, { query: { ...query, page, page_size: 500 } })
        if (!r.ok) throw new Error(`${path}: ${r.status} ${JSON.stringify(r.body)}`)
        rows.push(...r.body.results)
        if (!r.body.next) return rows
        page += 1
      }
    },
    /** Follow a Job until it is finished. Work runs inline today, so this normally returns at once. */
    async job(jobOrResponse, { timeoutMs = 120000 } = {}) {
      let job = jobOrResponse.body ?? jobOrResponse
      const stop = Date.now() + timeoutMs
      while (['PENDING', 'RUNNING'].includes(job.status) && Date.now() < stop) {
        await new Promise((r) => setTimeout(r, 750))
        job = (await call('GET', `/api/v1/jobs/${job.id}/`)).body
      }
      return job
    },
    /** How many calls came back as a server error, and which. A 5xx is always a finding. */
    serverErrors: () => calls.filter((c) => c.status >= 500),
    close: () => ctx.dispose(),
  }
  return session
}

/** A quick way to see what came back without dumping a whole page of rows. */
export function brief(result, keys) {
  const b = result.body
  if (!keys || !b || typeof b !== 'object') return `${result.status} ${JSON.stringify(b)?.slice(0, 300)}`
  return `${result.status} ${JSON.stringify(Object.fromEntries(keys.map((k) => [k, b[k]])))}`
}
