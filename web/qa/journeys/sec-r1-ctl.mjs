import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const ids = JSON.parse(readFileSync(process.env.TEMP + '/sec-ids.json'))
const SP = 'qa/samples'
const s = await login('staff'); const A = ids.Alpha
const rid = (await s.get(`/api/v1/clients/${A}/gst/runs/`)).body[0].id
const up = await s.upload(`/api/v1/clients/${A}/gst/runs/${rid}/register/`, SP + '/qa-sec-register-ctl.csv', {}, { mimeType: 'text/csv' })
console.log('upload', up.status)
console.log('reconcile', (await s.post(`/api/v1/clients/${A}/gst/runs/${rid}/reconcile/`, {})).status)
const ex = await s.get(`/api/v1/clients/${A}/gst/runs/${rid}/export/`)
console.log('export', ex.status, (ex.text||'').slice(0,100))
const rep = await s.get(`/api/v1/clients/${A}/gst/runs/${rid}/`); console.log('run json', rep.status)
// restore the normal register so the run is left in a usable state
console.log('restore', (await s.upload(`/api/v1/clients/${A}/gst/runs/${rid}/register/`, SP + '/qa-sec-register.csv', {}, { mimeType: 'text/csv' })).status)
