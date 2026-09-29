import { login } from '../lib/api.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const t0 = Date.now()
const r = await staff.upload(`api/v1/clients/${cid}/statements/upload/`, `qa/samples/qa-sca-kapoor-textiles-2025-06.pdf`)
console.log('JUNE upload elapsed', Date.now()-t0, r.status, JSON.stringify(r.body).slice(0,300))
if (r.status === 202) {
  const job = await staff.job(r)
  console.log('JUNE job', job.status, JSON.stringify(job.result ?? job).slice(0,900))
  writeFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-jun-job.json', JSON.stringify(job,null,2))
}
console.log('serverErrors', staff.serverErrors())
