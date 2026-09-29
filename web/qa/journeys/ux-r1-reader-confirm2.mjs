import { signedIn, shot, visibleText, WEB } from '../lib/session.mjs'
const { page, problems, close } = await signedIn('reader', { width: 1440, height: 900 })
const CID = 'd330689c-c0c6-4670-b8e8-69fcae492888'
await page.goto(`${WEB}/clients/${CID}`)
await page.waitForLoadState('networkidle')
const buttons = await page.locator('button').allTextContents()
console.log('BUTTONS:', JSON.stringify(buttons))
await close()
