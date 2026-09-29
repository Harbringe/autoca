import { request } from '@playwright/test'
import { PASSWORD, PEOPLE } from '../lib/session.mjs'
const API = 'http://127.0.0.1:8000'
async function sess(role) {
  const ctx = await request.newContext({ baseURL: API })
  const t0 = (await (await ctx.get('/auth/csrf/')).json()).csrfToken
  const before = (await ctx.storageState()).cookies.find(c=>c.name==='sessionid')?.value
  const r = await ctx.post('/auth/login/', { headers: { 'X-CSRFToken': t0 }, data: { email: PEOPLE[role], password: PASSWORD } })
  const st = await ctx.storageState()
  const after = st.cookies.find(c=>c.name==='sessionid')?.value
  const t1 = (await (await ctx.get('/auth/csrf/')).json()).csrfToken
  const cookies = Object.fromEntries(st.cookies.map(c=>[c.name,c]))
  return { ctx, t0, t1, sessBefore: before, sessAfter: after, login: r.status(), cookies }
}
const a = await sess('admin'), b = await sess('staff')
console.log('login', a.login, 'session cookie set pre-login?', !!a.sessBefore, ' rotated?', a.sessBefore !== a.sessAfter, ' csrf token rotated?', a.t0 !== a.t1)
console.log('cookie flags sessionid:', JSON.stringify({httpOnly:a.cookies.sessionid.httpOnly, sameSite:a.cookies.sessionid.sameSite, secure:a.cookies.sessionid.secure}), ' csrftoken:', JSON.stringify({httpOnly:a.cookies.csrftoken.httpOnly, sameSite:a.cookies.csrftoken.sameSite}))
const probe = { name: 'QA SEC csrf-probe', fy_start: '2025-04-01' }
const chk = async (label, ctx, headers, data = probe, path = '/api/v1/clients/') => {
  const r = await ctx.post(path, { headers, data })
  console.log(label.padEnd(58), r.status(), (await r.text()).slice(0,110).replace(/\s+/g,' '))
}
await chk('write, no header', a.ctx, {})
await chk('write, forged random 64-char header', a.ctx, { 'X-CSRFToken': 'A'.repeat(64) })
await chk('write, malformed short header', a.ctx, { 'X-CSRFToken': 'abc' })
await chk('write, STALE pre-login token', a.ctx, { 'X-CSRFToken': a.t0 })
await chk('write, other user (staff) session token in admin ctx', a.ctx, { 'X-CSRFToken': b.t1 })
await chk('write, valid token + hostile Origin', a.ctx, { 'X-CSRFToken': a.t1, Origin: 'http://evil.example' })
await chk('write, valid token + hostile Referer only', a.ctx, { 'X-CSRFToken': a.t1, Referer: 'http://evil.example/x' })
await chk('write, text/plain body no header (form-CSRF shape)', a.ctx, { 'Content-Type': 'text/plain' }, JSON.stringify(probe))
await chk('logout, no header', b.ctx, {}, {}, '/auth/logout/')
await chk('logout, forged header', b.ctx, { 'X-CSRFToken': 'B'.repeat(64) }, {}, '/auth/logout/')
await chk('logout, stale pre-login token', b.ctx, { 'X-CSRFToken': b.t0 }, {}, '/auth/logout/')
const still = await b.ctx.get('/api/v1/me/'); console.log('staff still signed in after refused logouts:', still.status())
// control: valid token DOES pass CSRF (409/400 from the app, not 403 CSRF) -- use logout at the end
const ok = await b.ctx.post('/auth/logout/', { headers: { 'X-CSRFToken': b.t1 } })
console.log('logout, valid token', ok.status())
const gone = await b.ctx.get('/api/v1/me/'); console.log('after logout /me:', gone.status())
// old session id replay after logout
const c2 = await request.newContext({ baseURL: API, extraHTTPHeaders: { Cookie: `sessionid=${b.cookies.sessionid.value}` } })
console.log('replay staff old sessionid after logout:', (await c2.get('/api/v1/me/')).status())
// session-fixation: attacker-chosen sessionid before login
const fx = await request.newContext({ baseURL: API, extraHTTPHeaders: { Cookie: 'sessionid=fixatedfixatedfixatedfixated0000' } })
const ft = (await (await fx.get('/auth/csrf/')).json()).csrfToken
const fl = await fx.post('/auth/login/', { headers: { 'X-CSRFToken': ft }, data: { email: PEOPLE.reader, password: PASSWORD } })
const fs = (await fx.storageState()).cookies.find(c=>c.name==='sessionid')?.value
console.log('fixation: login', fl.status(), 'new sessionid differs from planted:', fs !== 'fixatedfixatedfixatedfixated0000')
const c3 = await request.newContext({ baseURL: API, extraHTTPHeaders: { Cookie: 'sessionid=fixatedfixatedfixatedfixated0000' } })
console.log('planted id used by attacker afterwards:', (await c3.get('/api/v1/me/')).status())
// verify no probe client was created
const list = await a.ctx.get('/api/v1/clients/?search=csrf-probe'); console.log('probe clients existing:', (await list.json()).count)
