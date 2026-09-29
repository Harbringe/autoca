import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const stmts = await staff.all(`api/v1/clients/${cid}/statements/`)
const sid = stmts[0].id
const e1 = await staff.get(`api/v1/statements/${sid}/tally-export/`)
const e2 = await staff.get(`api/v1/statements/${sid}/tally-export/`)
const ids1 = [...e1.body.xml.matchAll(/REMOTEID="([^"]+)"/g)].map(m=>m[1])
const ids2 = [...e2.body.xml.matchAll(/REMOTEID="([^"]+)"/g)].map(m=>m[1])
console.log('count1', ids1.length, 'count2', ids2.length, 'same set', JSON.stringify([...ids1].sort()) === JSON.stringify([...ids2].sort()))
console.log('unique ids1', new Set(ids1).size)
// check narration present for every voucher
const noNarr = (e1.body.xml.match(/<NARRATION><\/NARRATION>/g) || []).length
console.log('vouchers with empty narration', noNarr)
console.log('serverErrors', staff.serverErrors())
