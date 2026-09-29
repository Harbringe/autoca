import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const stmts = await staff.all(`api/v1/clients/${cid}/statements/`)
console.log('statements', JSON.stringify(stmts, null, 2).slice(0,2000))
console.log('serverErrors', staff.serverErrors())
