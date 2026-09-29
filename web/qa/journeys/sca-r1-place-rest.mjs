import { login } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
const state = JSON.parse(readFileSync('C:/Users/count/AppData/Local/Temp/claude/E--autoca/4583afe5-fc20-4bd7-ad08-c97d2a3dcfab/scratchpad/sca-state.json'))
const cid = state.client.id
const staff = await login('staff')
const ledgers = await staff.all(`api/v1/clients/${cid}/ledgers/`)
const byName = n => ledgers.find(l => l.name === n)

const q = await staff.get(`api/v1/clients/${cid}/review-queue/`)
const rows = q.body.results

// map row_number -> desired ledger name (accept model's own where sensible)
const desired = {
  17: 'Sales', 13: 'Sales', 8: 'Sales', 2: 'Sales',
  14: 'GST Paid', 10: 'Salaries', 7: 'Rent', 3: 'Electricity Charges',
  11: 'Purchases', 5: 'Purchases', 12: 'Telephone & Internet',
  16: 'Postage & Courier', 15: 'Purchases', 4: 'Purchases', 18: 'Sales',
}

for (const r of rows) {
  const rn = r.transaction.row_number
  if (!(rn in desired)) continue
  const ledger = byName(desired[rn])
  if (!ledger) { console.log('MISSING LEDGER for', desired[rn]); continue }
  const res = await staff.post(`api/v1/classifications/${r.id}/review/`, { ledger: ledger.id, learn: true })
  console.log(rn, res.status, res.body.also_placed, res.body.rule_learned)
}

// try placing same row twice (idempotent / error?)
const dup = rows.find(r => r.transaction.row_number === 17)
const dupRes = await staff.post(`api/v1/classifications/${dup.id}/review/`, { ledger: byName('Sales').id, learn: false })
console.log('re-place row17', dupRes.status, JSON.stringify(dupRes.body).slice(0,200))

console.log('serverErrors', staff.serverErrors())
