import { login, brief } from '../lib/api.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
const ids = JSON.parse(readFileSync(process.env.TEMP + '/sec-ids.json'))
const a = await login('admin')
const cl = await a.get('/api/v1/classifications/', { statement: ids.Beta_st, page_size: 40 })
console.log('beta cls', cl.status, cl.body.count)
const rows = cl.body.results
console.log(rows.slice(0,3).map(r => ({id:r.id, m:r.method, led:r.ledger, posted:r.is_posted, nr:r.needs_review, band:r.review_band})))
const bLed = await a.get(`/api/v1/clients/${ids.Beta}/ledgers/`, { page_size: 200 })
const aLed = await a.get(`/api/v1/clients/${ids.Alpha}/ledgers/`, { page_size: 200 })
ids.Beta_ledgers = bLed.body.results.slice(0,6).map(l=>({id:l.id,name:l.name,status:l.status}))
ids.Alpha_ledgers = aLed.body.results.slice(0,6).map(l=>({id:l.id,name:l.name,status:l.status}))
console.log(JSON.stringify(ids.Beta_ledgers))
ids.Beta_cls = rows.map(r=>({id:r.id, posted:r.is_posted, ledger:r.ledger, method:r.method, band:r.review_band}))
writeFileSync(process.env.TEMP + '/sec-ids.json', JSON.stringify(ids))
