import { login } from '../lib/api.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
const ids = JSON.parse(readFileSync(process.env.TEMP + '/sec-ids.json'))
const SP = 'qa/samples'
const mine = readFileSync(SP + '/qa-sec-gstin.txt', 'utf8')
const s = await login('staff')
const A = ids.Alpha
const show = (l, r) => console.log(l.padEnd(30), r.status, (JSON.stringify(r.body)||'').slice(0,220))
const reg = await s.post(`/api/v1/clients/${A}/gst/registrations/`, { gstin: mine }); show('registration', reg)
let regId = reg.body?.id
if (!regId) { const l = await s.get(`/api/v1/clients/${A}/gst/registrations/`); regId = l.body[0].id }
const run = await s.post(`/api/v1/clients/${A}/gst/runs/`, { registration: regId, period: '2025-05' }); show('run', run)
const rid = run.body.id ?? run.body.run?.id
console.log('run id', rid, Object.keys(run.body).slice(0,8))
show('register upload', await s.upload(`/api/v1/clients/${A}/gst/runs/${rid}/register/`, SP + '/qa-sec-register.csv', {}, { mimeType: 'text/csv' }))
show('portal upload', await s.upload(`/api/v1/clients/${A}/gst/runs/${rid}/portal/`, SP + '/qa-sec-2b.csv', {}, { mimeType: 'text/csv' }))
show('reconcile', await s.post(`/api/v1/clients/${A}/gst/runs/${rid}/reconcile/`, {}))
const ex = await s.get(`/api/v1/clients/${A}/gst/runs/${rid}/export/`)
console.log('export', ex.status, ex.headers['content-type'], ex.headers['content-disposition'])
// text was decoded as utf-8; re-fetch as bytes through fetch on the same session cookie is not exposed, so re-request via ctx
