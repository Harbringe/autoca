import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const bankState = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-bank.json'))
const bankId = bankState.banks[0].id
const staff = await login('staff')
const r = await staff.post(`api/v1/clients/${cid}/bank-accounts/${bankId}/opening-balance/`, { opening_balance_paise: 15000000, opening_as_of: '2025-04-01' })
console.log('opening-balance', r.status, JSON.stringify(r.body).slice(0,500))
console.log('serverErrors', staff.serverErrors())
