import { signedIn, shot } from '../lib/session.mjs'

const CID = '73d99780-eca9-48e7-8ab2-a8e1cee1271f'
const { page, problems, close } = await signedIn('staff')
try {
  await page.goto(`http://127.0.0.1:5173/clients/${CID}/statements`)
  await page.waitForTimeout(500)
  await page.getByRole('button', { name: 'Upload bank statement' }).first().click()
  await page.waitForTimeout(400)
  await page.locator('input[type=file]').setInputFiles('qa/samples/qa-ca-ashok-enterprises-2026-05.pdf')
  await page.waitForTimeout(500)
  await page.getByRole('button', { name: 'Upload and read' }).click()
  await page.waitForTimeout(2000)
  for (let i = 0; i < 8; i++) {
    const t = await page.locator('body').innerText()
    if (!/Reading|Checking/.test(t)) break
    await page.waitForTimeout(3000)
  }
  await shot(page, 'r1-ca-upload-may-after')
  console.log((await page.locator('body').innerText()).slice(0, 2500))
} finally {
  console.log('problems:', problems)
  await close()
}
