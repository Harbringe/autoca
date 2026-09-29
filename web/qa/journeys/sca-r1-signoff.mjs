import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const senior = await login('senior')

const req = await staff.post(`api/v1/clients/${cid}/books/request/`, { note: 'Fixed salary narration, ready again' })
console.log('request2', req.status, JSON.stringify(req.body).slice(0,300))

const signoff = await senior.post(`api/v1/clients/${cid}/books/sign-off/`, { through_date: '2025-04-30' })
console.log('signoff', signoff.status, JSON.stringify(signoff.body).slice(0,700))

console.log('serverErrors', [staff, senior].flatMap(s=>s.serverErrors()))
