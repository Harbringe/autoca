import { signedIn, shot, visibleText, WEB } from '../lib/session.mjs'
const { page, problems, close } = await signedIn('reader', { width: 1440, height: 900 })
const CID = 'd330689c-c0c6-4670-b8e8-69fcae492888'
await page.goto(`${WEB}/clients/${CID}`)
await page.waitForLoadState('networkidle')
const btn = page.getByRole('button', { name: 'Confirm' })
console.log('enabled?', await btn.isEnabled())
await btn.click()
await page.waitForTimeout(1500)
console.log('after click url:', page.url())
console.log(await shot(page, 'r1-ux-reader-confirm-click'))
console.log((await visibleText(page)).slice(0, 1500))
console.log('PROBLEMS:', problems.join('\n') || 'none')
await close()
