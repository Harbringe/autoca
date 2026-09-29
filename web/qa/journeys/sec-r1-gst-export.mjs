import { request } from '@playwright/test'
import { writeFileSync, readFileSync } from 'node:fs'
import { PASSWORD, PEOPLE } from '../lib/session.mjs'
const ids = JSON.parse(readFileSync(process.env.TEMP + '/sec-ids.json'))
const SP = 'qa/samples'
const ctx = await request.newContext({ baseURL: 'http://127.0.0.1:8000' })
let t = (await (await ctx.get('/auth/csrf/')).json()).csrfToken
await ctx.post('/auth/login/', { headers: { 'X-CSRFToken': t }, data: { email: PEOPLE.staff, password: PASSWORD } })
const list = await ctx.get(`/api/v1/clients/${ids.Alpha}/gst/runs/`)
const rid = (await list.json())[0].id
const r = await ctx.get(`/api/v1/clients/${ids.Alpha}/gst/runs/${rid}/export/`)
writeFileSync('qa/samples/qa-sec-wp.xlsx', await r.body())
console.log(r.status())
