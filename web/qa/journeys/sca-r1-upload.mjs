import { login } from '../lib/api.mjs'
import { readFileSync, writeFileSync } from 'node:fs'

const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')

// list bank accounts before
const before = await staff.all(`api/v1/clients/${cid}/bank-accounts/`)
console.log('bank accounts before', before.length)

async function upload(file, label) {
  const r = await staff.upload(`api/v1/clients/${cid}/statements/upload/`, `qa/samples/${file}`)
  console.log(label, 'upload status', r.status, JSON.stringify(r.body).slice(0,300))
  if (r.status === 202) {
    const job = await staff.job(r)
    console.log(label, 'job', job.status, JSON.stringify(job.result ?? job).slice(0,600))
    return job
  }
  return r.body
}

const aprJob = await upload('qa-sca-kapoor-textiles-2025-04.pdf', 'APR')
writeFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-apr-job.json', JSON.stringify(aprJob, null, 2))

console.log('serverErrors', staff.serverErrors())
