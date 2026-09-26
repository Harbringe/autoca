// M2-009: unposting an entry from its dialog must not ask the server for that entry afterwards.
import { login } from '../lib/api.mjs'
import { signedIn, WEB } from '../lib/session.mjs'

const api = await login('staff')
const client = (await api.all('api/v1/clients/')).find((c) => c.name === 'QA Sharma Traders')
// Something to unpost: post one waiting row if nothing is posted yet.
let entries = (await api.all('api/v1/journal-entries/', { client: client.id, live: true })).filter((e) => !e.is_locked)
if (!entries.length) {
  const row = (await api.all(`api/v1/clients/${client.id}/review-queue/`, { stage: 'pending_approval' }))[0]
  await api.post(`api/v1/clients/${client.id}/approvals/`, { classifications: [row.id] })
  entries = (await api.all('api/v1/journal-entries/', { client: client.id, live: true })).filter((e) => !e.is_locked)
}
const target = entries[0]
const { page, problems, close } = await signedIn('staff')
try {
  await page.goto(`${WEB}/clients/${client.id}/daybook`)
  const show = page.getByRole('button', { name: /Show FY/ })
  await show.waitFor({ timeout: 5000 }).then(() => show.click()).catch(() => {})
  await page.getByText(target.narration.slice(0, 40)).first().click()
  await page.getByRole('button', { name: /Unpost \(back to Review\)/ }).click()
  problems.length = 0
  const after = []
  page.on('request', (r) => r.url().includes(target.id) && after.push(`${r.method()} ${r.url().replace(WEB, '')}`))
  await page.getByRole('dialog').getByRole('button', { name: /^Unpost$/ }).click()
  await page.getByText(/back in Review/).first().waitFor({ timeout: 30000 })
  await page.waitForTimeout(2500)
  const bad = after.filter((r) => !r.includes('/remove/'))
  console.log(bad.length === 0 && problems.length === 0 ? 'PASS  no request for the removed entry, no failed request' : `FAIL  ${[...bad, ...problems].join(' | ')}`)
} finally {
  await close()
  // Put it back: post the row again.
  const row = (await api.all(`api/v1/clients/${client.id}/review-queue/`)).find((r) => r.transaction.id === target.source_transaction)
  if (row?.ledger) await api.post(`api/v1/clients/${client.id}/approvals/`, { classifications: [row.id] })
  await api.close()
}
