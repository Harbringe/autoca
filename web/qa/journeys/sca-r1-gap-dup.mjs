import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')

// re-upload April (duplicate) - dup detection
const t0=Date.now()
const dup = await staff.upload(`api/v1/clients/${cid}/statements/upload/`, `qa/samples/qa-sca-kapoor-textiles-2025-04.pdf`)
console.log('dup upload elapsed', Date.now()-t0, dup.status, JSON.stringify(dup.body).slice(0,200))
if (dup.status===202) {
  const job = await staff.job(dup)
  console.log('dup job', JSON.stringify(job.result ?? job).slice(0,300))
}

// upload June with allow_gap true
const t1=Date.now()
const junR = await staff.upload(`api/v1/clients/${cid}/statements/upload/`, `qa/samples/qa-sca-kapoor-textiles-2025-06.pdf`, { allow_gap: 'true' })
console.log('june gap upload elapsed', Date.now()-t1, junR.status, JSON.stringify(junR.body).slice(0,200))
if (junR.status===202) {
  const job2 = await staff.job(junR)
  console.log('june job', JSON.stringify(job2.result ?? job2).slice(0,500))
}
console.log('serverErrors', staff.serverErrors())
