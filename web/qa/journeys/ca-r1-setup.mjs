// Create the two QA CA clients for r1, as admin, through the New client dialog.
import { signedIn, shot } from '../lib/session.mjs'

const NAMES = ['QA CA Ashok Enterprises', 'QA CA Bindal Traders']

const { page, problems, close } = await signedIn('admin')
try {
  for (const name of NAMES) {
    await page.getByRole('link', { name: 'Clients', exact: true }).click().catch(() => {})
    await page.goto(page.url().split('#')[0].replace(/\/clients.*/, '/clients'))
    await page.getByRole('button', { name: 'New client' }).click()
    await page.getByLabel(/Client name|Name/i).fill(name)
    // FY start default should be fine; submit
    const fy = page.getByLabel(/Financial year/i)
    if (await fy.count()) await fy.fill('2025-04-01').catch(() => {})
    await page.getByRole('button', { name: /^Create|Save|Add client$/i }).click()
    await page.waitForTimeout(1500)
    console.log('created?', name, page.url())
  }
  await shot(page, 'r1-ca-clients-after-create')
} finally {
  console.log('problems:', problems)
  await close()
}
