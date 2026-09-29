import { signedIn, visibleText, shot, WEB } from '../lib/session.mjs'
const { page, problems, close } = await signedIn('reader', { width: 1440, height: 900 })
const CID = 'd330689c-c0c6-4670-b8e8-69fcae492888'
await page.goto(`${WEB}/clients/${CID}/review`)
await page.waitForLoadState('networkidle')
await page.locator('button:has-text("Check")').first().click()
await page.waitForTimeout(600)
console.log(await shot(page, 'r1-ux-reader-decision-panel'))
const postBtn = page.getByRole('button', { name: /Post entry/i })
console.log('Post entry count:', await postBtn.count())
if (await postBtn.count()) console.log('enabled?', await postBtn.first().isEnabled())
const confirmBtn = page.getByRole('button', { name: /Confirm ledger/i })
console.log('Confirm ledger count:', await confirmBtn.count())
if (await confirmBtn.count()) console.log('enabled?', await confirmBtn.first().isEnabled())
// attempt to click post entry to see result
if (await postBtn.count() && await postBtn.first().isEnabled()) {
  await postBtn.first().click()
  await page.waitForTimeout(1200)
  console.log('AFTER CLICK:', (await visibleText(page)).slice(0,800))
  console.log('PROBLEMS:', problems.join('\n') || 'none')
}
await close()
