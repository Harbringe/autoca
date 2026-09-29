import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const entries = await staff.all(`api/v1/journal-entries/`, { client: cid })
console.log('entries count', entries.length)
for (const e of entries) console.log(JSON.stringify(e).slice(0,500))
console.log('serverErrors', staff.serverErrors())
