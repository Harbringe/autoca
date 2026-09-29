import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')

const reg = await staff.post(`api/v1/clients/${cid}/gst/registrations/`, { gstin: '27ABCDE1234F1Z5' })
console.log('registration', reg.status, JSON.stringify(reg.body).slice(0,300))

if (reg.status === 201) {
  const run = await staff.post(`api/v1/clients/${cid}/gst/runs/`, { registration: reg.body.id, period: '2025-04' })
  console.log('run', run.status, JSON.stringify(run.body).slice(0,500))
}
console.log('serverErrors', staff.serverErrors())
