import { request } from '@playwright/test'
const ctx = await request.newContext({ baseURL: 'http://127.0.0.1:8000' })
const t = (await (await ctx.get('/auth/csrf/')).json()).csrfToken
for (let i = 1; i <= 5; i++) {
  const t0 = Date.now()
  const r = await ctx.post('/auth/login/', { headers: { 'X-CSRFToken': t }, data: { email: 'qa.sec.nobody@autoca.test', password: 'wrong-' + i } })
  console.log(i, r.status(), Date.now() - t0, 'ms', r.headers()['retry-after'] ?? '', (await r.text()).slice(0, 100))
}
