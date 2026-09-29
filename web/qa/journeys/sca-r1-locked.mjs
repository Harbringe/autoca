import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const senior = await login('senior')

const entries = await staff.all(`api/v1/journal-entries/`, { client: cid })
const target = entries[0]

const c = await staff.post(`api/v1/journal-entries/${target.id}/correct/`, { treatment: { ledger: target.lines[0].ledger_id ?? target.lines[0].ledger, learn: false } })
console.log('correct locked entry (expect 409)', c.status, JSON.stringify(c.body).slice(0,200))

const rm = await staff.post(`api/v1/journal-entries/${target.id}/remove/`, {})
console.log('remove locked entry (expect 409)', rm.status, JSON.stringify(rm.body).slice(0,200))

const stmts = await staff.all(`api/v1/clients/${cid}/statements/`)
const delR = await staff.del(`api/v1/statements/${stmts[0].id}/`)
console.log('delete statement (expect refused)', delR.status, JSON.stringify(delR.body).slice(0,200))

console.log('serverErrors', [staff, senior].flatMap(s=>s.serverErrors()))
