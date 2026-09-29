import { signedIn, shot, visibleText } from '../lib/session.mjs'
const { page, problems, close } = await signedIn('senior')
await page.goto('http://127.0.0.1:5173/clients/591f73c7-35a5-42cf-9998-b5fc55ca1799')
await page.waitForTimeout(800)
await shot(page, 'sca-r1-overview-after-june-signoff')
console.log(await visibleText(page))
console.log('problems', problems)
await close()
