import { signedIn, shot, WEB } from '../lib/session.mjs'
const { page, close } = await signedIn('admin', { width: 1440, height: 900 })
const CID = 'd330689c-c0c6-4670-b8e8-69fcae492888'
await page.goto(`${WEB}/clients/${CID}/review`)
await page.waitForLoadState('networkidle')
const cell = page.locator('td', { hasText: 'NEFT CR-ICIC0000456-LOTU' }).first()
const title = await cell.getAttribute('title')
console.log('title attr:', title)
const full = await cell.innerText()
console.log('cell text:', full)
// try hovering
await cell.hover()
await page.waitForTimeout(600)
await page.screenshot({ path: 'qa/screenshots/r1-ux-narration-hover.png' })
await close()
