import { signedIn, shot } from '../lib/session.mjs'

const CID = '73d99780-eca9-48e7-8ab2-a8e1cee1271f'
const { page, problems, close } = await signedIn('staff')
try {
  await page.goto(`http://127.0.0.1:5173/clients/${CID}`)
  await page.waitForTimeout(500)
  await page.getByRole('link', { name: 'Confirm', exact: true }).click()
  await page.waitForTimeout(800)
  console.log('url', page.url())
  console.log('page text:\n', (await page.locator('body').innerText()).slice(0, 2500))
  await shot(page, 'r1-ca-statements-page')
} finally {
  console.log('problems:', problems)
  await close()
}
