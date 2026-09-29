import { signedIn, shot, visibleText } from '../lib/session.mjs'
const { page, problems, close } = await signedIn('reader')
const r = await page.goto('http://127.0.0.1:5173/clients')
await page.waitForTimeout(500)
console.log(await visibleText(page))
console.log('problems', problems)
await close()
