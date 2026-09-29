import { login } from '../lib/api.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')

const tb = await staff.get(`api/v1/clients/${cid}/reports/trial-balance/`, { fy: 2025 })
console.log('TB', tb.status, JSON.stringify(tb.body).slice(0,1500))
const pl = await staff.get(`api/v1/clients/${cid}/reports/profit-and-loss/`, { fy: 2025 })
console.log('PL', pl.status, JSON.stringify(pl.body).slice(0,1500))
const bs = await staff.get(`api/v1/clients/${cid}/reports/balance-sheet/`, { fy: 2025 })
console.log('BS', bs.status, JSON.stringify(bs.body).slice(0,1500))

writeFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-reports.json', JSON.stringify({tb: tb.body, pl: pl.body, bs: bs.body}, null, 2))
console.log('serverErrors', staff.serverErrors())
