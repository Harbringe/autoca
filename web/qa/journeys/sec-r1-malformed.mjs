import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const ids = JSON.parse(readFileSync(process.env.TEMP + '/sec-ids.json'))
const SP = 'qa/samples'
const s = await login('staff'); const A = ids.Alpha
const list = await s.get(`/api/v1/clients/${A}/gst/runs/`); const rid = list.body[0].id
const show = (l, r) => console.log(l.padEnd(44), r.status, (typeof r.body==='string'? r.body.slice(0,80).replace(/\s+/g,' ') : JSON.stringify(r.body)).slice(0,150))
for (const m of ['[1]', '"x"', '{"gstin": ["a"]}', '{"gstin": 5}', 'null', '{"invoice_no":"Invoice No"}']) {
  show('register mapping=' + m, await s.upload(`/api/v1/clients/${A}/gst/runs/${rid}/register/`, SP + '/qa-sec-register.csv', { mapping: m }, { mimeType: 'text/csv' }))
}
show('bad uuid path', await s.get(`/api/v1/clients/not-a-uuid/`))
show('decision bad body', await s.post(`/api/v1/clients/${A}/gst/runs/${rid}/decisions/`, 'not json'))
show('register as .xlsx garbage', await s.uploadBytes(`/api/v1/clients/${A}/gst/runs/${rid}/register/`, Buffer.from('PK\x03\x04garbage'), 'x.xlsx', 'application/octet-stream'))
show('portal json huge nesting', await s.uploadBytes(`/api/v1/clients/${A}/gst/runs/${rid}/portal/`, Buffer.from('['.repeat(200000)), 'x.json', 'application/json'))
show('portal json wrong types', await s.uploadBytes(`/api/v1/clients/${A}/gst/runs/${rid}/portal/`, Buffer.from('{"data":{"docdata":{"b2b":[{"inv":"x"}]}}}'), 'x.json', 'application/json'))
show('portal json list', await s.uploadBytes(`/api/v1/clients/${A}/gst/runs/${rid}/portal/`, Buffer.from('[1,2]'), 'x.json', 'application/json'))
show('portal json b2b not list', await s.uploadBytes(`/api/v1/clients/${A}/gst/runs/${rid}/portal/`, Buffer.from('{"data":{"docdata":{"b2b":5}}}'), 'x.json', 'application/json'))
show('portal json supplier is str', await s.uploadBytes(`/api/v1/clients/${A}/gst/runs/${rid}/portal/`, Buffer.from('{"data":{"docdata":{"b2b":["x"]}}}'), 'x.json', 'application/json'))
console.log('5xx:', JSON.stringify(s.serverErrors()))
