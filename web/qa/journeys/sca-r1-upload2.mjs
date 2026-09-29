import { login } from '../lib/api.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
import { request } from '@playwright/test'

const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')

async function uploadSlow(file) {
  // reuse staff's cookies via a fresh context sharing storageState
  const storageState = await staff.__ctx?.storageState?.()
  return null
}

// Instead: find csrftoken/sessionid via headers isn't exposed; just call staff.upload but bump via direct fetch using node fetch with cookies extracted from calls
console.log('trying upload with default client but logging start time')
const t0 = Date.now()
const r = await staff.upload(`api/v1/clients/${cid}/statements/upload/`, `qa/samples/qa-sca-kapoor-textiles-2025-04.pdf`)
console.log('elapsed ms', Date.now() - t0, 'status', r.status, JSON.stringify(r.body).slice(0,400))
if (r.status === 202) {
  const job = await staff.job(r)
  console.log('job', job.status, JSON.stringify(job.result ?? job).slice(0,800))
  writeFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-apr-job.json', JSON.stringify(job, null, 2))
}
console.log('serverErrors', staff.serverErrors())
