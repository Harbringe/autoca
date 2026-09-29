import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const q = await staff.get(`api/v1/clients/${cid}/review-queue/`)
console.log('remaining in queue', q.body.count)
for (const r of q.body.results) console.log(r.id, r.transaction.row_number, r.ledger_name, r.review_band, r.needs_review)
console.log('serverErrors', staff.serverErrors())
