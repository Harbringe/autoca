import { login } from '../lib/api.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const banks = await staff.all(`api/v1/clients/${cid}/bank-accounts/`)
console.log('bank accounts', JSON.stringify(banks, null, 2))
const stmts = await staff.all(`api/v1/clients/${cid}/statements/`)
console.log('statements', JSON.stringify(stmts, null, 2).slice(0, 1500))
writeFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-bank.json', JSON.stringify({banks, stmts}, null, 2))
console.log('serverErrors', staff.serverErrors())
