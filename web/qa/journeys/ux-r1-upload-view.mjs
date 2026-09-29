import { signedIn, WEB, SHOTS } from '../lib/session.mjs'
const { page, close } = await signedIn('admin')
const CID = 'd330689c-c0c6-4670-b8e8-69fcae492888'
await page.goto(`${WEB}/clients/${CID}/review`); await page.waitForTimeout(1200)
await page.getByRole('button', { name: 'Upload bank statement' }).click(); await page.waitForTimeout(600)
await page.screenshot({ path: SHOTS + '/r1-ux-upload-dialog.png' })
console.log(await page.locator('[role=dialog]').innerText())
console.log(await page.locator('[role=dialog]').ariaSnapshot())
await page.keyboard.press('Escape'); await page.waitForTimeout(300)
console.log('dialog after esc', await page.locator('[role=dialog]').count(), 'focus', await page.evaluate(()=>document.activeElement.innerText.slice(0,30)))
await close()
