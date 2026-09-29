import { signedIn, visibleText, shot, WEB } from '../lib/session.mjs'
const { page, close } = await signedIn('reader', { width: 1440, height: 900 })
const CID = 'd330689c-c0c6-4670-b8e8-69fcae492888'
await page.goto(`${WEB}/clients/${CID}/statements`)
await page.waitForLoadState('networkidle')
console.log('--- statements as reader ---')
console.log((await visibleText(page)).slice(0,1000))
console.log(await shot(page, 'r1-ux-reader-statements'))

await page.goto(`${WEB}/clients/${CID}/review`)
await page.waitForLoadState('networkidle')
console.log('--- review as reader ---')
console.log((await visibleText(page)).slice(0,1500))
console.log(await shot(page, 'r1-ux-reader-review'))
const checks = await page.locator('button:has-text("Check")').count()
console.log('Check buttons count:', checks)
if (checks) {
  const first = page.locator('button:has-text("Check")').first()
  console.log('enabled?', await first.isEnabled())
}
await close()
