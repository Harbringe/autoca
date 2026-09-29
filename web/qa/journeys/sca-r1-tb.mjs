import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const entries = await staff.all(`api/v1/journal-entries/`, { client: cid })
console.log('journal entries count', entries.length)
let sumDr=0,sumCr=0
for (const e of entries) {
  for (const l of e.lines) { if (l.direction==='DR') sumDr+=l.amount_paise; else sumCr+=l.amount_paise }
}
console.log('sum dr', sumDr, 'sum cr', sumCr)

const q = await staff.get(`api/v1/clients/${cid}/review-queue/`)
console.log('remaining in queue', q.body.count)

console.log('serverErrors', staff.serverErrors())
