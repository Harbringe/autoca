import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const ledgers = await staff.all(`api/v1/clients/${cid}/ledgers/`)
const purchases = ledgers.find(l => l.name === 'Purchases')
const bank = ledgers.find(l => l.group === 'BANK' || l.group_name === 'Bank Accounts')
console.log('purchases', purchases?.id, 'bank', JSON.stringify(bank))

// row1 zepto classification id
const rowId = 'b17f1be3-7936-4824-aa54-1dab4ce5aee6'
const r = await staff.post(`api/v1/classifications/${rowId}/review/`, { ledger: purchases.id, learn: true })
console.log('place row1 status', r.status, JSON.stringify(r.body).slice(0,800))

// try placing another row into bank ledger itself (must refuse)
const bankLedger = ledgers.find(l => l.name === 'Generic Bank A/c 0001')
const r2 = await staff.post(`api/v1/classifications/9cb20d65-8770-49d3-af44-d725134f61d5/review/`, { ledger: bankLedger.id, learn: false })
console.log('place into bank ledger (should refuse)', r2.status, JSON.stringify(r2.body).slice(0,400))

console.log('serverErrors', staff.serverErrors())
