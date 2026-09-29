import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const q = await staff.get(`api/v1/clients/${cid}/review-queue/`)
console.log('queue count', q.body.count)
for (const r of q.body.results) console.log(r.transaction.row_number, r.transaction.narration.slice(0,40), r.ledger_name, r.needs_review, r.is_posted, r.method)

const entries = await staff.all(`api/v1/journal-entries/`, { client: cid, live: 'true' })
console.log('live journal entries total', entries.length)
const juneEntries = entries.filter(e => e.entry_date >= '2025-06-01' && e.entry_date <= '2025-06-30')
console.log('june entries', juneEntries.length)
for (const e of juneEntries) console.log(e.entry_date, e.voucher_type, e.entry_no, e.narration.slice(0,60))
console.log('serverErrors', staff.serverErrors())
