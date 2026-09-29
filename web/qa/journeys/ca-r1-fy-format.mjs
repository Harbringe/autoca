// Check what happens when the "Financial year starts" field gets a non DD-MM-YYYY string.
import { signedIn, shot } from '../lib/session.mjs'

const { page, problems, close } = await signedIn('admin')
try {
  await page.goto(page.url().replace(/\/clients.*/, '/clients'))
  await page.getByRole('button', { name: 'New client' }).click()
  await page.waitForTimeout(300)
  await page.getByLabel('Client name').fill('QA CA Format Probe (delete me)')
  await page.getByLabel('Financial year starts').fill('2025-04-01')
  await page.waitForTimeout(200)
  const value = await page.getByLabel('Financial year starts').inputValue()
  console.log('field value after fill with 2025-04-01:', JSON.stringify(value))
  const errText = await page.locator('[role=dialog]').innerText()
  console.log('dialog text:\n', errText)
  await shot(page, 'r1-ca-fy-format-before-submit')
  // Try to submit
  await page.getByRole('button', { name: 'Add client' }).click()
  await page.waitForTimeout(1200)
  console.log('after submit, url:', page.url())
  const stillOpen = await page.locator('[role=dialog]').count()
  console.log('dialog still open?', stillOpen)
  if (stillOpen) {
    console.log('dialog text after submit attempt:\n', await page.locator('[role=dialog]').innerText())
    await shot(page, 'r1-ca-fy-format-after-submit-blocked')
    await page.getByRole('button', { name: 'Cancel' }).click()
  }
} finally {
  console.log('problems:', problems)
  await close()
}
