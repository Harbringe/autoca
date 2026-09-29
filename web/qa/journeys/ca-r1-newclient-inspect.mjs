import { signedIn, shot } from '../lib/session.mjs'

const { page, problems, close } = await signedIn('admin')
try {
  await page.goto(page.url().replace(/\/clients.*/, '/clients'))
  await page.getByRole('button', { name: 'New client' }).click()
  await page.waitForTimeout(300)
  const html = await page.locator('[role=dialog]').innerHTML().catch(() => 'no dialog')
  console.log(html.slice(0, 4000))
  await shot(page, 'r1-ca-newclient-dialog')
} finally {
  console.log('problems:', problems)
  await close()
}
