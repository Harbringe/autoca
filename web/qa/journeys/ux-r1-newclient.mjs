import { signedIn, WEB, SHOTS } from '../lib/session.mjs'
const { page, close } = await signedIn('admin')
await page.goto(`${WEB}/clients`); await page.waitForTimeout(1000)
await page.getByRole('button', { name: /New client/ }).click().catch(async()=>page.getByRole('link',{name:/New client/}).click())
await page.waitForTimeout(600)
await page.screenshot({ path: SHOTS + '/r1-ux-newclient.png' })
console.log(await page.locator('[role=dialog]').innerText().catch(()=>page.locator('main').innerText()))
// submit empty
await page.getByRole('button', { name: /^(Create|Add|Save)/ }).first().click().catch(()=>{})
await page.waitForTimeout(500)
await page.screenshot({ path: SHOTS + '/r1-ux-newclient-empty-submit.png' })
console.log('FOCUS', await page.evaluate(()=>document.activeElement.outerHTML.slice(0,150)))
console.log(await page.locator('[role=dialog]').innerText().catch(()=>''))
await close()
