import { signedIn, shot, visibleText } from '../lib/session.mjs'
const CID='8b70e7ab-e10d-40ac-818c-9cdf9112db03'
const { page, problems, close } = await signedIn('admin')
await page.goto(`http://127.0.0.1:5173/clients/${CID}`); await page.waitForTimeout(800)
console.log((await visibleText(page)).slice(300,1800))
await page.getByRole('button', { name: /Upload/ }).first().click(); await page.waitForTimeout(500)
await shot(page,'r1-ca-bindal-upload-dialog'); console.log('DIALOG', (await visibleText(page)).slice(-900))
await page.locator('input[type=file]').setInputFiles('qa/samples/qa-ca-bindal-traders-2026-03.pdf'); await page.waitForTimeout(400)
await page.getByRole('button', { name: 'Upload and read' }).click(); await page.waitForTimeout(7000)
await shot(page,'r1-ca-bindal-upload-done'); console.log('AFTER', (await visibleText(page)).slice(-1800))
console.log(problems); await close()
