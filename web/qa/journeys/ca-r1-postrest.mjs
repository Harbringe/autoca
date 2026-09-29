import { signedIn, shot, visibleText } from '../lib/session.mjs'
const CID='8b70e7ab-e10d-40ac-818c-9cdf9112db03'
const { page, problems, close } = await signedIn('admin')
await page.goto(`http://127.0.0.1:5173/clients/${CID}/review`); await page.waitForTimeout(1500)
await page.locator('thead input[type=checkbox], [role=columnheader] input[type=checkbox]').first().check(); await page.waitForTimeout(500)
await shot(page,'r1-ca-review-selected'); 
console.log((await visibleText(page)).slice(0,1500))
console.log(await page.getByRole('button').allInnerTexts())

await page.getByRole('button', { name: 'Post 5 ticked' }).click(); await page.waitForTimeout(800)
await shot(page,'r1-ca-post5-confirm'); console.log((await visibleText(page)).slice(-700))

await page.getByRole('button', { name: 'Post 5', exact: true }).click(); await page.waitForTimeout(3000)
console.log((await visibleText(page)).slice(300,900))
console.log(problems); await close()
