import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const ledgers = await staff.all(`api/v1/clients/${cid}/ledgers/`)
const purchases = ledgers.find(l => l.name === 'Purchases')
// re-place row1 (idempotent?) to see also_placed field explicitly
const r = await staff.post(`api/v1/classifications/b17f1be3-7936-4824-aa54-1dab4ce5aee6/review/`, { ledger: purchases.id, learn: true })
console.log(JSON.stringify(r.body, null, 2))
console.log('serverErrors', staff.serverErrors())
