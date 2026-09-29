import { signedIn, WEB } from '../lib/session.mjs'
const { page, close } = await signedIn('reader', { width: 1440, height: 900 })
const CID = 'd330689c-c0c6-4670-b8e8-69fcae492888'
await page.goto(`${WEB}/clients/${CID}`)
await page.waitForLoadState('networkidle')
const el = page.locator('text=Confirm').last()
const html = await el.evaluate(e => e.outerHTML)
console.log(html)
const el2 = page.locator('text=Post').last()
console.log(await el2.evaluate(e => e.outerHTML))
await close()
