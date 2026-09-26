import { setTransport } from '@/platform/http'
import { apiFetch, onSessionChange, raw, resetCsrf } from './client'
import { ApiError } from './errors'

function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })
}

/** A fake server: records what it was sent and answers from a queue. */
function server(answer: (request: Request, n: number) => Response) {
  const seen: Request[] = []
  setTransport(async (request) => {
    seen.push(request.clone())
    return answer(request, seen.length)
  })
  return seen
}

afterEach(() => {
  resetCsrf()
  setTransport((request) => fetch(request))
})

describe('apiFetch', () => {
  it('sends the CSRF token on a mutating request, and none on a read', async () => {
    const seen = server((request) => (request.url.endsWith('/auth/csrf/') ? json({ csrfToken: 'tok-1' }) : json({ ok: true })))
    await raw.get('/api/v1/me/')
    await raw.post('/api/v1/clients/', { name: 'X' })
    const read = seen.find((r) => r.method === 'GET' && r.url.endsWith('/api/v1/me/'))!
    const write = seen.find((r) => r.method === 'POST' && r.url.endsWith('/api/v1/clients/'))!
    expect(read.headers.get('X-CSRFToken')).toBeNull()
    expect(write.headers.get('X-CSRFToken')).toBe('tok-1')
  })

  it('asks for a fresh token once when Django refuses a stale one, then succeeds', async () => {
    let issued = 0
    const seen = server((request) => {
      if (request.url.endsWith('/auth/csrf/')) return json({ csrfToken: `tok-${++issued}` })
      return request.headers.get('X-CSRFToken') === 'tok-2' ? json({ done: true }) : json({ detail: 'CSRF Failed: token missing.' }, 403)
    })
    const result = await raw.post<{ done: boolean }>('/api/v1/clients/', { name: 'X' })
    expect(result.done).toBe(true)
    expect(issued).toBe(2)
    expect(seen.filter((r) => r.url.endsWith('/api/v1/clients/'))).toHaveLength(2)
  })

  it('does not retry forever: a second CSRF refusal is an error', async () => {
    server((request) => (request.url.endsWith('/auth/csrf/') ? json({ csrfToken: 't' }) : json({ detail: 'CSRF Failed' }, 403)))
    await expect(raw.post('/api/v1/clients/', {})).rejects.toBeInstanceOf(ApiError)
  })

  it('throws the server’s own sentence as an ApiError, with its code and field errors', async () => {
    server(() => json({ code: 'invalid', detail: 'Some fields are invalid.', fields: { name: ['Already exists.'] } }, 400))
    const error = (await raw.get('/api/v1/clients/').catch((e: unknown) => e)) as ApiError
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(400)
    expect(error.message).toBe('Some fields are invalid.')
    expect(error.field('name')).toBe('Already exists.')
  })

  it('reads Retry-After from a lockout', async () => {
    server(() => json({ code: 'too_many_attempts', detail: 'Too many attempts.' }, 429, { 'Retry-After': '900' }))
    const error = (await raw.get('/api/v1/me/').catch((e: unknown) => e)) as ApiError
    expect(error.retryAfter).toBe(900)
  })

  it('tells the session when it is signed out or short of a second factor, but not for a wrong password', async () => {
    const heard: string[] = []
    const off = onSessionChange((e) => heard.push(e.code))
    server((request) => {
      const path = new URL(request.url).pathname
      if (path === '/auth/csrf/') return json({ csrfToken: 't' })
      if (path === '/auth/login/') return json({ code: 'invalid_credentials', detail: 'Invalid credentials.' }, 401)
      return json({ code: 'mfa_required', detail: 'Enter your code.' }, 403)
    })
    await raw.post('/auth/login/', {}).catch(() => undefined)
    expect(heard).toEqual([])
    await raw.get('/api/v1/me/').catch(() => undefined)
    expect(heard).toEqual(['mfa_required'])
    off()
  })

  it('returns undefined for a 204', async () => {
    server((request) => (request.url.endsWith('/auth/csrf/') ? json({ csrfToken: 't' }) : new Response(null, { status: 204 })))
    await expect(raw.delete('/api/v1/clients/x/')).resolves.toBeUndefined()
  })

  it('is usable directly with a Request, as the generated client calls it', async () => {
    server(() => json({ hello: 'world' }))
    const response = await apiFetch(new Request('http://localhost/api/v1/me/'))
    expect(await response.json()).toEqual({ hello: 'world' })
  })
})
