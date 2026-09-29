import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const senior = await login('senior')

const req = await staff.post(`api/v1/clients/${cid}/books/request/`, { note: 'June auto-posted by rules, requesting review' })
console.log('request', req.status, JSON.stringify(req.body).slice(0,300))

const signoffAttempt = await senior.post(`api/v1/clients/${cid}/books/sign-off/`, { through_date: '2025-06-30' })
console.log('signoff attempt before mark-reviewed', signoffAttempt.status, JSON.stringify(signoffAttempt.body).slice(0,400))

console.log('serverErrors', [staff, senior].flatMap(s=>s.serverErrors()))
