import { request } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { PASSWORD, PEOPLE } from '../lib/session.mjs'
const ids = JSON.parse(readFileSync(process.env.TEMP + '/sec-ids.json'))
const SP = 'qa/samples'
const ctx = await request.newContext({ baseURL: 'http://127.0.0.1:8000', timeout: 590000 })
let tok = (await (await ctx.get('/auth/csrf/')).json()).csrfToken
await ctx.post('/auth/login/', { headers: {'X-CSRFToken': tok}, data: { email: PEOPLE.admin, password: PASSWORD } })
tok = (await (await ctx.get('/auth/csrf/')).json()).csrfToken
const t = Date.now()
const r = await ctx.post(`/api/v1/clients/${ids.Beta}/statements/upload/`, { headers: {'X-CSRFToken': tok}, multipart: { file: { name: 'qa-sec-2000pages.pdf', mimeType: 'application/pdf', buffer: readFileSync(SP + '/qa-sec-2000pages.pdf') } } })
console.log(r.status(), Date.now()-t, 'ms', (await r.text()).slice(0,500))
