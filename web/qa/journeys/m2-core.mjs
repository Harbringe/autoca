// The core loop, through the screens, as the senior CA on QA Gupta Exports:
// upload a statement -> confirm the opening balance -> place every row -> post -> check the
// Day Book, Trial Balance and bank reconciliation against the API -> send for review -> sign off.
//
//   node qa/tools/make-statement.mjs --holder "QA GUPTA EXPORTS" --account 91820000777777   (once)
//   node qa/journeys/m2-core.mjs
//
// Repeatable: it first takes back anything a previous run left on the client (through the API).

import { resolve } from 'node:path'
import { login } from '../lib/api.mjs'
import { shot, signedIn, WEB } from '../lib/session.mjs'

const PDF = resolve(import.meta.dirname, '..', 'samples', 'qa-gupta-exports-2025-04.pdf')
const CLIENT = 'QA Gupta Exports'
const results = []
const check = (name, ok, detail = '') => {
  results.push(ok)
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  (${detail})` : ''}`)
}

// --- reset, through the API ----------------------------------------------------------------------
const api = await login('senior')
const client = (await api.all('api/v1/clients/')).find((c) => c.name === CLIENT)
for (let i = 0; i < 10; i += 1) {
  const b = (await api.get(`api/v1/clients/${client.id}/books/`)).body
  if (!b.signed_off_through) break
  await api.post(`api/v1/clients/${client.id}/books/reopen/`, { note: 'QA journey reset' })
}
for (const s of await api.all(`api/v1/clients/${client.id}/statements/`)) await api.del(`api/v1/clients/${client.id}/statements/${s.id}/`)
for (const r of await api.all(`api/v1/clients/${client.id}/rules/`)) if (r.source !== 'SEED') await api.del(`api/v1/clients/${client.id}/rules/${r.id}/`)
const SEEDED = new Set(['Bank Interest Received', 'Bank Charges', 'Cash-in-Hand', 'Suspense A/c'])
for (const l of await api.all(`api/v1/clients/${client.id}/ledgers/`)) if (!SEEDED.has(l.name) && l.group !== 'BANK') await api.del(`api/v1/clients/${client.id}/ledgers/${l.id}/`)

// --- the screens ---------------------------------------------------------------------------------
const { page, problems, close } = await signedIn('senior')
try {
  await page.goto(`${WEB}/clients/${client.id}`)
  await page.getByText('Upload bank statements').waitFor()
  check('Overview starts at step 1, upload', (await page.locator('li', { hasText: 'Next step' }).innerText()).includes('Upload bank statements'))

  // Upload
  await page.getByRole('button', { name: 'Upload bank statement' }).first().click()
  await page.getByText('What to upload').waitFor()
  await page.locator('input[type=file]').setInputFiles(PDF)
  await page.getByRole('button', { name: 'Upload and read' }).click()
  await page.getByText(/Imported \d+ transactions|Already imported/).waitFor({ timeout: 120000 })
  const imported = await page.getByRole('dialog').innerText()
  check('upload reports the rows read', /Imported 20 transactions/.test(imported), imported.match(/Imported \d+ transactions/)?.[0])
  check('upload shows the period in DD-MM-YYYY', /01-04-2025 to 30-04-2025/.test(imported))
  await shot(page, 'm2j-upload-done')

  // Opening balance, straight from the upload result
  const opening = page.getByRole('button', { name: 'Confirm opening balance' })
  const asked = await opening.isVisible()
  const known = (await api.all(`api/v1/clients/${client.id}/bank-accounts/`)).every((a) => a.has_opening_balance)
  check('asks for the opening balance exactly when it is not yet known', asked !== known, asked ? 'asked' : 'already confirmed earlier')
  if (asked) {
    await opening.click()
    await page.getByText('Confirm the opening balance').waitFor({ state: 'detached' })
    check('opening balance confirmed from the upload result', true)
  }
  await page.getByRole('button', { name: 'Close' }).first().click()

  // Place every row that has no ledger, with the keyboard
  await page.goto(`${WEB}/clients/${client.id}/review?stage=unresolved`)
  await page.waitForLoadState('networkidle')
  await page.getByText(/Every transaction has a ledger|The entry this makes/).first().waitFor()
  let placed = 0
  for (let guard = 0; guard < 30; guard += 1) {
    if (await page.getByText('Every transaction has a ledger').isVisible()) break
    await page.keyboard.press('l')
    await page.keyboard.type('Miscellaneous Expenses')
    await page.waitForTimeout(200)
    await page.keyboard.press('Enter') // pick from the list, or create it
    const create = page.getByRole('button', { name: 'Create and use' })
    if (await create.isVisible().catch(() => false)) {
      await shot(page, 'm2j-create-ledger')
      await create.click()
      await page.waitForTimeout(800)
    }
    if (guard === 0) await shot(page, 'm2j-before-place')
    await page.locator('body').click({ position: { x: 5, y: 5 } }) // leave the input, so Enter means "place"
    await page.getByRole('checkbox', { name: /Remember this/ }).uncheck().catch(() => {})
    await page.keyboard.press('Enter')
    await page.waitForTimeout(900)
    placed += 1
  }
  check('every row placed through the screen', await page.getByText('Every transaction has a ledger').isVisible(), `${placed} placed by keyboard`)

  // Always place at least one by keyboard, whatever the assistant did: re-decide a suggested row.
  if (placed === 0) {
    await page.goto(`${WEB}/clients/${client.id}/review?stage=pending_approval`)
    await page.getByText('The entry this makes').waitFor()
    await page.keyboard.press('l')
    await page.keyboard.type('Miscellaneous Expenses')
    await page.waitForTimeout(300)
    await page.keyboard.press('Enter')
    const create = page.getByRole('button', { name: 'Create and use' })
    if (await create.isVisible().catch(() => false)) {
      await create.click()
      await page.waitForTimeout(800)
    }
    await page.getByRole('checkbox', { name: /Remember this/ }).uncheck()
    await page.keyboard.press('Enter')
    await page.waitForTimeout(1500)
    placed = 1
  }
  const decided = (await api.all(`api/v1/clients/${client.id}/review-queue/`)).filter((r) => r.method === 'REVIEWED')
  check('a row was placed by keyboard and is recorded as a person’s decision', decided.length >= 1, `${decided.length} reviewed`)
  const cpin = (await api.all(`api/v1/clients/${client.id}/review-queue/`)).concat([]).find((r) => /CPIN/.test(r.transaction.narration))
  const cpinPosted = (await api.all('api/v1/journal-entries/', { client: client.id, live: true })).find((e) => /CPIN/.test(e.narration) && e.lines.some((l) => l.ledger_name === 'Bank Charges'))
  check('the GST challan payment was not posted to Bank Charges', !cpinPosted, cpin ? `waiting in review as ${cpin.ledger_name ?? 'unplaced'}` : '')

  // Post everything
  await page.goto(`${WEB}/clients/${client.id}/review?stage=pending_approval`)
  await page.waitForLoadState('networkidle')
  await page.getByRole('checkbox', { name: 'Tick every row that can be posted' }).check()
  await page.getByRole('button', { name: /Post \d+ ticked/ }).click()
  await page.getByRole('dialog').getByRole('button', { name: /^Post \d+$/ }).click()
  await page.getByText('Nothing is waiting here').waitFor({ timeout: 60000 })
  check('everything posted', true)

  // The year banner and the Day Book
  await page.goto(`${WEB}/clients/${client.id}/daybook`)
  const show = page.getByRole('button', { name: /Show FY 2025-26/ })
  await show.waitFor({ timeout: 10000 }).then(() => show.click()).catch(() => {})
  check('the year banner offered FY 2025-26', true)
  await page.waitForLoadState('networkidle')
  const live = (await api.all('api/v1/journal-entries/', { client: client.id, live: true })).filter((e) => e.financial_year === 2025)
  const dayBookRows = await page.locator('tbody tr').count()
  check('Day Book lists every posted entry', dayBookRows === live.length, `${dayBookRows} on screen, ${live.length} from the API`)
  await shot(page, 'm2j-daybook')

  // Unpost what the assistant posted, from the Day Book, then post it again from Review
  const aiBefore = live.filter((e) => e.marker && !e.is_locked)
  if (aiBefore.length) {
    await page.goto(`${WEB}/clients/${client.id}/daybook`)
    await page.getByRole('button', { name: /Unpost \d+ assistant-posted/ }).click()
    await page.getByRole('dialog').getByRole('button', { name: /^Unpost \d+$/ }).click()
    await page.getByText(/back in Review/).first().waitFor({ timeout: 60000 })
    const after = await api.all('api/v1/journal-entries/', { client: client.id, live: true })
    const queue = await api.all(`api/v1/clients/${client.id}/review-queue/`)
    check('bulk unpost takes every assistant entry out of the books', after.every((e) => !e.marker), `${aiBefore.length} unposted`)
    check('and their transactions are back in Review', queue.length >= aiBefore.length, `${queue.length} waiting`)
    await page.goto(`${WEB}/clients/${client.id}/review?stage=pending_approval`)
    await page.getByRole('checkbox', { name: 'Tick every row that can be posted' }).check()
    await page.getByRole('button', { name: /Post \d+ ticked/ }).click()
    await page.getByRole('dialog').getByRole('button', { name: /^Post \d+$/ }).click()
    await page.getByText('Nothing is waiting here').waitFor({ timeout: 60000 })
    check('and can be posted again, this time by a person', true)
  } else {
    check('bulk unpost (no assistant entries this run to try it on)', true)
  }

  // Trial Balance
  await page.goto(`${WEB}/clients/${client.id}/reports?report=tb`)
  await page.getByText('Grand Total').waitFor()
  const tb = (await api.get(`api/v1/clients/${client.id}/reports/trial-balance/`, { fy: 2025 })).body
  const tbText = await page.locator('main').innerText()
  check('Trial Balance tallies (API)', tb.balances && tb.total_debit_paise === tb.total_credit_paise, tb.total_debit_display)
  check('Trial Balance totals on screen equal the API', tbText.includes(tb.total_debit_display) && tbText.includes(tb.total_credit_display))
  check('Trial Balance says "as at 31-03-2026"', tbText.includes('as at 31-03-2026'))
  await shot(page, 'm2j-tb')

  await page.goto(`${WEB}/clients/${client.id}/reports?report=pl`)
  await page.getByText(/Net (Profit|Loss) for the year/).first().waitFor()
  await shot(page, 'm2j-pl')
  await page.goto(`${WEB}/clients/${client.id}/reports?report=bs`)
  await page.getByText('Liabilities').first().waitFor()
  const bs = (await api.get(`api/v1/clients/${client.id}/reports/balance-sheet/`, { fy: 2025 })).body
  check('Balance Sheet balances (API)', bs.balances, `${bs.total_assets_display} / ${bs.total_liabilities_and_profit_display}`)
  await shot(page, 'm2j-bs')

  // Reconciliation
  await page.goto(`${WEB}/clients/${client.id}/reports?report=recon`)
  await page.getByText('Difference', { exact: true }).first().waitFor({ timeout: 20000 })
  const recon = await page.locator('main').innerText()
  check('bank reconciliation at 30-04-2025 matches', /₹0\.00/.test(recon.split('Difference')[1] ?? ''), recon.split('Difference')[1]?.trim().split('\n')[0])
  await shot(page, 'm2j-recon')

  // Send for review, then sign off (the senior leads this client, so may do both)
  await page.goto(`${WEB}/clients/${client.id}/books`)
  await page.getByRole('button', { name: 'Send for review' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Send for review' }).click()
  await page.getByRole('button', { name: 'Sign off the books' }).waitFor()
  await page.getByRole('button', { name: 'Sign off the books' }).click()
  const started = Date.now()
  await page.getByRole('dialog').getByRole('button', { name: 'Sign off' }).click()
  await page.getByText(/Signed off through/).first().waitFor({ timeout: 30000 })
  check('sign-off completes promptly', Date.now() - started < 10000, `${((Date.now() - started) / 1000).toFixed(1)} s`)
  await shot(page, 'm2j-books')

  check('no console errors or failed requests along the way', problems.length === 0, problems.join(' | '))
} finally {
  await close()
  await api.close()
}
const failed = results.filter((ok) => !ok).length
console.log(failed ? `\n${failed} FAILED` : '\nall passed')
process.exit(failed ? 1 : 0)
