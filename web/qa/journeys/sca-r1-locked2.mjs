import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const senior = await login('senior')

const entries = await staff.all(`api/v1/journal-entries/`, { client: cid })
const target = entries[0]
console.log('target line0', JSON.stringify(target.lines[0]))

const c = await staff.post(`api/v1/journal-entries/${target.id}/correct/`, { treatment: { ledger: target.lines[0].ledger_account, learn: false } })
console.log('correct locked entry (expect 409)', c.status, JSON.stringify(c.body).slice(0,300))

const stmts = await staff.all(`api/v1/clients/${cid}/statements/`)
const delR = await staff.del(`api/v1/clients/${cid}/statements/${stmts[0].id}/`)
console.log('delete statement (expect refused)', delR.status, JSON.stringify(delR.body).slice(0,300))

// role checks: staff return/sign-off on signed-off client
const staffReturn = await staff.post(`api/v1/clients/${cid}/books/return/`, { note: 'x' })
console.log('staff return (expect 403)', staffReturn.status, JSON.stringify(staffReturn.body).slice(0,150))
const staffSignoff = await staff.post(`api/v1/clients/${cid}/books/sign-off/`, {})
console.log('staff sign-off (expect 403)', staffSignoff.status, JSON.stringify(staffSignoff.body).slice(0,150))

// reopen
const reopen = await senior.post(`api/v1/clients/${cid}/books/reopen/`, { note: 'Need to fix the ATM contra narration wording' })
console.log('reopen', reopen.status, JSON.stringify(reopen.body).slice(0,400))

// now correction should work
const c2 = await staff.post(`api/v1/journal-entries/${target.id}/correct/`, { treatment: { ledger: target.lines[0].ledger_account, learn: false }, narration: 'Being cash withdrawn from bank at Pune Camp for petty cash' })
console.log('correct after reopen', c2.status, JSON.stringify(c2.body).slice(0,400))

// sign off again
const req3 = await staff.post(`api/v1/clients/${cid}/books/request/`, { note: 'Reopened fix done' })
console.log('request3', req3.status)
const signoff2 = await senior.post(`api/v1/clients/${cid}/books/sign-off/`, { through_date: '2025-04-30' })
console.log('signoff2', signoff2.status, JSON.stringify(signoff2.body).slice(0,400))

console.log('serverErrors', [staff, senior].flatMap(s=>s.serverErrors()))
