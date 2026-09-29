import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const ids = JSON.parse(readFileSync(process.env.TEMP + '/sec-ids.json'))
const B = ids.Beta, A = ids.Alpha
const show = (l, r) => console.log(l.padEnd(46), r.status, (JSON.stringify(r.body)||'').slice(0,260))
const s = await login('staff'), se = await login('senior'), ad = await login('admin')
show('admin books Beta', await ad.get(`/api/v1/clients/${B}/books/`))
show('senior request Beta (member)', await se.post(`/api/v1/clients/${B}/books/request/`, {note:'QA SEC'}))
show('senior sign-off Beta (member, non-lead)', await se.post(`/api/v1/clients/${B}/books/sign-off/`, {}))
show('senior return Beta (member, non-lead)', await se.post(`/api/v1/clients/${B}/books/return/`, {note:'x'}))
show('staff request Alpha', await s.post(`/api/v1/clients/${A}/books/request/`, {note:'QA SEC'}))
show('staff sign-off Alpha (requested)', await s.post(`/api/v1/clients/${A}/books/sign-off/`, {}))
show('admin books Beta', await ad.get(`/api/v1/clients/${B}/books/`))
show('admin books Alpha', await ad.get(`/api/v1/clients/${A}/books/`))
// return both so nothing is left pending
show('admin return Beta', await ad.post(`/api/v1/clients/${B}/books/return/`, {note:'QA SEC probe done'}))
show('admin return Alpha', await ad.post(`/api/v1/clients/${A}/books/return/`, {note:'QA SEC probe done'}))
