import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const pr = await staff.post(`api/v1/clients/${cid}/parties/`, { canonical_name: 'Zepto Marketplace' })
console.log('create party', pr.status, JSON.stringify(pr.body).slice(0,300))
const partyId = pr.body.id

const confirm = await staff.post(`api/v1/classifications/0d202bf7-2711-49bf-a0d2-025e037a5ae8/confirm-party/`, { party: partyId })
console.log('confirm-party row9', confirm.status, JSON.stringify(confirm.body).slice(0,500))

const ledgers = await staff.all(`api/v1/clients/${cid}/ledgers/`)
const purchases = ledgers.find(l => l.name === 'Purchases')
const place = await staff.post(`api/v1/classifications/0d202bf7-2711-49bf-a0d2-025e037a5ae8/review/`, { ledger: purchases.id, party: partyId, learn: true })
console.log('place row9 with party+learn', place.status, JSON.stringify({also_placed: place.body.also_placed, also_revised: place.body.also_revised, rule_learned: place.body.rule_learned}))

const q = await staff.get(`api/v1/clients/${cid}/review-queue/`)
for (const r of q.body.results) console.log(r.transaction.row_number, r.counterparty, r.ledger_name, r.needs_review, r.party_resolution)
console.log('serverErrors', staff.serverErrors())
