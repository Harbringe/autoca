#!/usr/bin/env node
// Take the statement-review client's statements back out, through the API, as a person would:
// the senior reopens the books if they are signed off, then staff remove each statement.
// Posted entries go with it (each logged); the stored file is deleted by the server.
//
//   node qa/tools/cleanup-statement.mjs
//
// Reads the client id from qa/private/statement-client.json (written by the reviewer).

import { readFileSync } from 'node:fs'
import { login } from '../lib/api.mjs'

const { client } = JSON.parse(readFileSync(new URL('../private/statement-client.json', import.meta.url), 'utf8'))
const senior = await login('senior')
const staff = await login('staff')

// Reopen undoes one sign-off at a time, so keep going until nothing is locked.
for (let round = 1; round <= 10; round += 1) {
  const books = await senior.get(`api/v1/clients/${client}/books/`)
  const through = books.body?.signed_off_through ?? null
  console.log(`books: signed off through ${through}`)
  if (!through) break
  const reopened = await senior.post(`api/v1/clients/${client}/books/reopen/`, { note: 'QA cleanup: removing the review statement.' })
  console.log('  reopen:', reopened.status, reopened.ok ? '' : `${reopened.body?.code}: ${reopened.body?.detail}`)
  if (!reopened.ok) break
}

const statements = await staff.all(`api/v1/clients/${client}/statements/`)
console.log(`${statements.length} statement(s) to remove`)
for (const s of statements) {
  const r = await staff.del(`api/v1/clients/${client}/statements/${s.id}/`)
  console.log('remove', s.id.slice(0, 8), r.status, r.ok ? JSON.stringify({ rows: r.body.rows, entries: r.body.entries, account_now_empty: r.body.account_now_empty }) : `${r.body?.code}: ${r.body?.detail}`)
}
const left = await staff.all(`api/v1/clients/${client}/statements/`)
console.log('statements left:', left.length)
// What was learned along the way (payee-keyed rules, parties, the chart the reviewer built) goes too,
// so the next round starts from the seeded chart and behaves as a first upload.
const SEEDED = new Set(['Bank Interest Received', 'Bank Charges', 'Cash-in-Hand', 'Suspense A/c'])
for (const rule of await staff.all(`api/v1/clients/${client}/rules/`)) await staff.del(`api/v1/clients/${client}/rules/${rule.id}/`)
for (const party of await staff.all(`api/v1/clients/${client}/parties/`)) await staff.del(`api/v1/clients/${client}/parties/${party.id}/`)
let kept = 0
for (const ledger of await staff.all(`api/v1/clients/${client}/ledgers/`)) {
  if (SEEDED.has(ledger.name)) continue
  const r = await staff.del(`api/v1/clients/${client}/ledgers/${ledger.id}/`)
  if (!r.ok) kept += 1
}
console.log(`rules left: ${(await staff.all(`api/v1/clients/${client}/rules/`)).filter((r) => r.source !== 'SEED').length}; parties left: ${(await staff.all(`api/v1/clients/${client}/parties/`)).length}; ledgers that could not be removed: ${kept}`)
await senior.close()
await staff.close()
