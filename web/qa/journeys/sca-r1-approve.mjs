import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')

const q = await staff.get(`api/v1/clients/${cid}/review-queue/`)
const rows = q.body.results
const highIds = rows.filter(r=>r.review_band==='HIGH').map(r=>r.id)
const others = rows.filter(r=>r.review_band!=='HIGH').map(r=>r.id)
console.log('HIGH count', highIds.length, 'others', others.length)

const byBand = await staff.post(`api/v1/clients/${cid}/approvals/`, { band: 'HIGH' })
console.log('approve band HIGH', byBand.status, JSON.stringify(byBand.body).slice(0,500))

const byIds = await staff.post(`api/v1/clients/${cid}/approvals/`, { classifications: others })
console.log('approve rest by ids', byIds.status, JSON.stringify(byIds.body).slice(0,500))

// approve same again (double approve)
const again = await staff.post(`api/v1/clients/${cid}/approvals/`, { classifications: others })
console.log('approve same ids again', again.status, JSON.stringify(again.body).slice(0,400))

console.log('serverErrors', staff.serverErrors())
