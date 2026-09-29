import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const bankState = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-bank.json'))
const bankId = bankState.banks[0].id
const staff = await login('staff')
const r = await staff.get(`api/v1/bank-accounts/${bankId}/reconciliation/`, { as_of: '2025-04-30' })
console.log('recon', r.status, JSON.stringify(r.body, null, 2))
console.log('serverErrors', staff.serverErrors())
