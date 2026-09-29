import { signedIn, shot, visibleText, WEB } from '../lib/session.mjs'

const { page, problems, close } = await signedIn('admin', { width: 1440, height: 900 })
await page.goto(`${WEB}/clients`)
await page.waitForLoadState('networkidle')
// click first non-QA-Statement-Review, non-seeded client row to see client overview nav
await page.getByRole('link', { name: /QA Sharma Traders/ }).click()
await page.waitForLoadState('networkidle')
await page.waitForTimeout(500)
console.log('URL:', page.url())
console.log(await shot(page, 'r1-ux-client-overview-admin'))
console.log(await visibleText(page))
console.log('PROBLEMS:', problems.join('\n') || 'none')
await close()
