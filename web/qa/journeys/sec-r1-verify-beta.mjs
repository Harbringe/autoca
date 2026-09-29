import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const ids = JSON.parse(readFileSync(process.env.TEMP + '/sec-ids.json'))
const a = await login('admin')
const c = await a.get(`/api/v1/classifications/${ids.Beta_cls[3].id}/`)
console.log('cls[3] now', c.status, 'ledger', c.body.ledger, 'method', c.body.method, '| recorded', ids.Beta_cls[3].ledger, ids.Beta_cls[3].method, ids.Beta_cls[3].posted, 'posted now', c.body.is_posted)
const ch = await a.get(`/api/v1/journal-entries/${ids.Beta_je}/changes/`)
console.log('JE changes', ch.status, JSON.stringify(ch.body).slice(0, 500))
const pl = await a.get(`/api/v1/clients/${ids.Beta}/parties/`); const lg = await a.get(`/api/v1/clients/${ids.Beta}/ledgers/`, {page_size:200})
console.log('Beta parties', pl.body.count, 'ledgers has staff-created?', JSON.stringify(lg.body.results.some(l=>/QA SEC (staff|hacked)/.test(l.name))))
const cl = await a.get(`/api/v1/clients/${ids.Beta}/`); console.log('Beta name', cl.body.name)
