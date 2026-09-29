import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const entries = await staff.all(`api/v1/journal-entries/`, { client: cid })
const salary = entries.find(e => e.narration?.toLowerCase().includes('salar'))
console.log('salary entry', salary.id, salary.narration, JSON.stringify(salary.lines.map(l=>({d:l.direction,l:l.ledger_name,p:l.amount_paise}))))

const ledgers = await staff.all(`api/v1/clients/${cid}/ledgers/`)
const salariesLedger = ledgers.find(l => l.name === 'Salaries')
const bankLedger = ledgers.find(l => l.name === 'Generic Bank A/c 0001')

const corrReq = { treatment: { ledger: salariesLedger.id, learn: false }, narration: 'Being salary for April 2025 paid to staff in bulk by NEFT' }
const c = await staff.post(`api/v1/journal-entries/${salary.id}/correct/`, corrReq)
console.log('correct', c.status, JSON.stringify(c.body).slice(0,700))

// check original entry still visible + changes log
const changes = await staff.get(`api/v1/journal-entries/${salary.id}/changes/`)
console.log('changes', changes.status, JSON.stringify(changes.body).slice(0,800))

const entries2 = await staff.all(`api/v1/journal-entries/`, { client: cid })
console.log('entries count now (live default)', entries2.length)
const entriesAll = await staff.all(`api/v1/journal-entries/`, { client: cid, live: undefined })
console.log('serverErrors', staff.serverErrors())
