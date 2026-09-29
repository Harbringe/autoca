import { signedIn, shot, visibleText } from '../lib/session.mjs'
const CID='8b70e7ab-e10d-40ac-818c-9cdf9112db03'
const { page, problems, close } = await signedIn('admin')
await page.goto(`http://127.0.0.1:5173/clients/${CID}/review`); await page.waitForTimeout(1500)
await page.getByRole('button', { name: /Post all high-confidence/ }).click(); await page.waitForTimeout(700)
await shot(page,'r1-ca-postall-confirm'); console.log((await visibleText(page)).slice(-1000))

await page.getByRole('button', { name: 'Post 12', exact: true }).click(); await page.waitForTimeout(2500)
await shot(page,'r1-ca-postall-done'); console.log((await visibleText(page)).slice(-500))
console.log(problems); await close()
