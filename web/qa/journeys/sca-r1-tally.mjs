import { login } from '../lib/api.mjs'
import { readFileSync, writeFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const stmts = await staff.all(`api/v1/clients/${cid}/statements/`)
const sid = stmts[0].id
const e1 = await staff.get(`api/v1/statements/${sid}/tally-export/`)
console.log('export1', e1.status, 'voucher_count', e1.body.voucher_count, 'ledger_count', e1.body.ledger_count, 'unapproved', JSON.stringify(e1.body.unapproved))
const e2 = await staff.get(`api/v1/statements/${sid}/tally-export/`)
console.log('export2', e2.status, 'voucher_count', e2.body.voucher_count)

const re1 = [...e1.body.xml.matchAll(/<REMOTEID>([^<]+)<\/REMOTEID>/g)].map(m=>m[1])
const re2 = [...e2.body.xml.matchAll(/<REMOTEID>([^<]+)<\/REMOTEID>/g)].map(m=>m[1])
console.log('remoteids equal?', JSON.stringify(re1) === JSON.stringify(re2), re1.length, re2.length)

writeFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-tally.xml', e1.body.xml)
console.log('serverErrors', staff.serverErrors())
