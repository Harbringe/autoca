import { signedIn, shot, visibleText } from '../lib/session.mjs'
const { page, problems, close } = await signedIn('senior')
await page.goto('http://127.0.0.1:5173/clients/591f73c7-35a5-42cf-9998-b5fc55ca1799/reports')
await page.getByText('Show FY 2025-26').click()
await page.waitForTimeout(800)
await shot(page, 'sca-r1-reports-fy25-clicked')
console.log(await visibleText(page))
console.log('problems', problems)
await close()
