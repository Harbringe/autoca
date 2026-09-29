import { login } from '../lib/api.mjs'
import { readFileSync, writeFileSync } from 'node:fs'

const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const admin = await login('admin')

const senior = '8ad13e4b-4cd5-4232-934c-618d4abf9f18'
const staff = '2deb2029-235c-468d-a41a-63607bed65e1'

const leadR = await admin.put(`api/v1/team/clients/${cid}/lead/`, { lead: senior })
console.log('set lead', leadR.status, JSON.stringify(leadR.body))

const teamR = await admin.post(`api/v1/team/clients/${cid}/team/`, { member: staff })
console.log('assign staff', teamR.status, JSON.stringify(teamR.body))

// visibility check
const seniorS = await login('senior')
const staffS = await login('staff')
const readerS = await login('reader')
const seniorSee = await seniorS.get(`api/v1/clients/${cid}/`)
const staffSee = await staffS.get(`api/v1/clients/${cid}/`)
const readerSee = await readerS.get(`api/v1/clients/${cid}/`)
console.log('senior sees', seniorSee.status, 'staff sees', staffSee.status, 'reader sees', readerSee.status)

// QA Patel & Sons should 404 for senior and staff
const clientsAdmin = await admin.all('api/v1/clients/')
const patel = clientsAdmin.find(c => c.name === 'QA Patel & Sons')
const seniorPatel = await seniorS.get(`api/v1/clients/${patel.id}/`)
const staffPatel = await staffS.get(`api/v1/clients/${patel.id}/`)
console.log('patel: senior', seniorPatel.status, 'staff', staffPatel.status)

console.log('serverErrors', [admin, seniorS, staffS, readerS].flatMap(s=>s.serverErrors()))
