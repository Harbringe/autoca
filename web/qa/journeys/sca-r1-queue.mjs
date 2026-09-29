import { login } from '../lib/api.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const q = await staff.get(`api/v1/clients/${cid}/review-queue/`)
console.log('queue status', q.status)
console.log(JSON.stringify(q.body, null, 2).slice(0, 4000))
writeFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-queue.json', JSON.stringify(q.body, null, 2))
const summary = await staff.get(`api/v1/clients/${cid}/summary/`)
console.log('summary', summary.status, JSON.stringify(summary.body).slice(0,800))
const ledgers = await staff.all(`api/v1/clients/${cid}/ledgers/`)
console.log('ledgers count', ledgers.length, JSON.stringify(ledgers.slice(0,30).map(l=>({n:l.name,g:l.group_name ?? l.group}))))
console.log('serverErrors', staff.serverErrors())
