import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const entries = await staff.all(`api/v1/journal-entries/`, { client: cid, live: 'true' })
const byType = {}
for (const e of entries) { (byType[e.voucher_type] ??= []).push(e.entry_no) }
for (const [t, nums] of Object.entries(byType)) {
  nums.sort((a,b)=>a-b)
  console.log(t, nums.join(','))
}
console.log('total live entries', entries.length)
console.log('serverErrors', staff.serverErrors())
