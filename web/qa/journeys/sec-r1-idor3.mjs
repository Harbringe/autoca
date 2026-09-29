import { login, brief } from '../lib/api.mjs'
import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
const ids = JSON.parse(readFileSync(process.env.TEMP + '/sec-ids.json'))
const B = ids.Beta, A = ids.Alpha
const a = await login('admin')
async function snap() {
  const g = async p => JSON.stringify((await a.get(p, {page_size:200})).body)
  const parts = [
    `/api/v1/clients/${B}/`, `/api/v1/clients/${B}/bank-accounts/${ids.Beta_ba}/`, `/api/v1/clients/${B}/ledgers/`,
    `/api/v1/clients/${B}/parties/`, `/api/v1/clients/${B}/rules/`, `/api/v1/clients/${B}/statements/`,
    `/api/v1/classifications/`, `/api/v1/journal-entries/`, `/api/v1/clients/${B}/books/`, `/api/v1/audit/`,
  ]
  const out = {}
  for (const p of parts) out[p] = createHash('sha1').update(await g(p)).digest('hex').slice(0,8)
  return out
}
const before = await snap()
const s = await login('staff')
const U = '00000000-0000-4000-8000-000000000001'
const tests = [
  ['PATCH', `/api/v1/clients/${B}/`, { name: 'QA SEC hacked' }],
  ['PUT', `/api/v1/clients/${B}/`, { name: 'QA SEC hacked', fy_start:'2025-04-01' }],
  ['DELETE', `/api/v1/clients/${B}/`],
  ['PATCH', `/api/v1/clients/${B}/bank-accounts/${ids.Beta_ba}/`, { ledger_name: 'QA SEC hacked' }],
  ['DELETE', `/api/v1/clients/${B}/bank-accounts/${ids.Beta_ba}/`],
  ['POST', `/api/v1/clients/${B}/ledgers/`, { name: 'QA SEC staff ledger', group: 'DIRECT_EXPENSE' }],
  ['PATCH', `/api/v1/clients/${B}/ledgers/${ids.Beta_led}/`, { name: 'QA SEC hacked' }],
  ['DELETE', `/api/v1/clients/${B}/ledgers/${ids.Beta_led}/`],
  ['POST', `/api/v1/clients/${B}/ledgers/${ids.Beta_led}/reject/`, {}],
  ['POST', `/api/v1/clients/${B}/ledgers/${ids.Beta_led}/accept/`, {}],
  ['POST', `/api/v1/clients/${B}/ledgers/${ids.Beta_led}/merge/`, {into: ids.Beta_ledgers[1].id}],
  ['POST', `/api/v1/clients/${B}/parties/`, { canonical_name: 'QA SEC staff party' }],
  ['POST', `/api/v1/clients/${B}/rules/`, { }],
  ['POST', `/api/v1/clients/${B}/review-queue/suggest/`, {}],
  ['POST', `/api/v1/clients/${B}/review-queue/recategorize/`, {}],
  ['POST', `/api/v1/classifications/${ids.Beta_cls[3].id}/review/`, { ledger: ids.Beta_ledgers[0].id, rcm: false, learn: false }],
  ['POST', `/api/v1/classifications/${ids.Beta_cls[3].id}/confirm-party/`, { party: U }],
  ['POST', `/api/v1/clients/${B}/approvals/`, { classifications: [ids.Beta_cls[1].id] }],
  ['POST', `/api/v1/clients/${B}/approvals/`, { band: 'HIGH' }],
  ['POST', `/api/v1/journal-entries/${ids.Beta_je}/correct/`, { treatment: { ledger: ids.Beta_ledgers[0].id, rcm: false } }],
  ['POST', `/api/v1/journal-entries/${ids.Beta_je}/remove/`, { note: 'x' }],
  ['POST', `/api/v1/clients/${B}/books/request/`, {}],
  ['POST', `/api/v1/clients/${B}/books/return/`, { note: 'x' }],
  ['POST', `/api/v1/clients/${B}/books/sign-off/`, {}],
  ['POST', `/api/v1/clients/${B}/books/reopen/`, { note: 'x' }],
  ['POST', `/api/v1/clients/${B}/books/mark-reviewed/`, {}],
  ['DELETE', `/api/v1/clients/${B}/statements/${ids.Beta_st}/`],
  ['POST', `/api/v1/clients/${B}/gst/registrations/`, { gstin: '27AAPFU0939F1ZV' }],
  ['GET', `/api/v1/clients/${B}/statements/${ids.Beta_st}/`],
  ['GET', `/api/v1/statements/${ids.Beta_st}/tally-export/`],
  ['GET', `/api/v1/bank-accounts/${ids.Beta_ba}/reconciliation/`],
  ['GET', `/api/v1/journal-entries/${ids.Beta_je}/`],
  ['GET', `/api/v1/journal-entries/${ids.Beta_je}/changes/`],
  ['GET', `/api/v1/clients/${B}/reports/trial-balance/`],
  ['GET', `/api/v1/clients/${B}/books/`],
  ['GET', `/api/v1/clients/${B}/gst/registrations/`],
  ['GET', `/api/v1/classifications/${ids.Beta_cls[0].id}/`],
  ['GET', `/api/v1/transactions/`],
]
for (const [m, p, d] of tests) {
  const r = await s.call ? null : null
  const res = m === 'GET' ? await s.get(p) : m === 'POST' ? await s.post(p, d) : m === 'PATCH' ? await s.patch(p, d) : m === 'PUT' ? await s.put(p, d) : await s.del(p)
  let extra = ''
  if (p.endsWith('/api/v1/transactions/')) extra = ` count=${res.body?.count} anyBeta=${JSON.stringify(res.body?.results?.some(t=>t.bank_account===ids.Beta_ba))}`
  console.log(m.padEnd(6), res.status, p.replace(B,'<BETA>').replace(/[0-9a-f-]{36}/g,'<id>'), (JSON.stringify(res.body)||'').slice(0,90), extra)
}
// upload to Beta as staff
const up = await s.upload(`/api/v1/clients/${B}/statements/upload/`, 'qa/samples/qa-sec-beta-2025-04.pdf')
console.log('UPLOAD staff->Beta', up.status, JSON.stringify(up.body).slice(0,100))
const after = await snap()
for (const k of Object.keys(before)) if (before[k] !== after[k]) console.log('CHANGED', k.replace(B,'<BETA>'))
console.log('snapshot diff done; server errors:', s.serverErrors().length)
