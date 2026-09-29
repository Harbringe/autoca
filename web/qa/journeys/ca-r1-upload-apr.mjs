// Upload April 2026 statement for QA CA Ashok Enterprises, as staff, through the actual screen.
import { signedIn, shot } from '../lib/session.mjs'

const CID = '73d99780-eca9-48e7-8ab2-a8e1cee1271f'
const { page, problems, close } = await signedIn('staff')
try {
  await page.goto(`http://127.0.0.1:5173/clients/${CID}`)
  await page.waitForTimeout(500)
  await page.getByRole('button', { name: 'Upload a statement' }).click()
  await page.waitForTimeout(400)
  const input = page.locator('input[type=file]')
  await input.setInputFiles('qa/samples/qa-ca-ashok-enterprises-2026-04.pdf')
  await page.waitForTimeout(500)
  const submitBtn = page.getByRole('button', { name: 'Upload and read' })
  await submitBtn.click()
  await page.waitForTimeout(6000)
  await shot(page, 'r1-ca-upload-apr-after')
  console.log('body text after:\n', (await page.locator('body').innerText()).slice(0, 3000))
  console.log('url', page.url())
} finally {
  console.log('problems:', problems)
  await close()
}
