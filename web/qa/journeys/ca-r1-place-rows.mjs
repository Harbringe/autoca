// Place the 6 "needs a ledger" rows for QA CA Ashok Enterprises, as staff, through the screen.
import { signedIn, shot } from '../lib/session.mjs'

const CID = '73d99780-eca9-48e7-8ab2-a8e1cee1271f'
const { page, problems, close } = await signedIn('staff')
try {
  await page.goto(`http://127.0.0.1:5173/clients/${CID}/review`)
  await page.waitForTimeout(800)
  await page.getByRole('button', { name: /Needs a ledger/i }).click().catch(() => {})
  await page.waitForTimeout(500)

  for (let i = 0; i < 8; i++) {
    const text = await page.locator('body').innerText()
    const m = text.match(/Needs a ledger (\d+)/)
    console.log('remaining needs-a-ledger:', m ? m[1] : '?')
    if (m && m[1] === '0') break

    // Open the first row in the list
    const rows = page.locator('table tbody tr, [data-row]')
    // Use the ledger combobox visible in the detail pane on the right
    const ledgerInput = page.getByRole('combobox', { name: /Ledger \(the other side/i }).first()
    if (!(await ledgerInput.count())) {
      console.log('no ledger combobox found; dumping text')
      console.log(text.slice(0, 3000))
      break
    }
    await ledgerInput.click()
    await page.waitForTimeout(300)
    await ledgerInput.fill('Miscellaneous')
    await page.waitForTimeout(500)
    const options = page.getByRole('option')
    const count = await options.count()
    console.log('options for Miscellaneous:', count)
    if (count > 0) {
      await options.first().click()
    } else {
      await page.keyboard.press('Escape')
      await ledgerInput.fill('Suspense')
      await page.waitForTimeout(500)
      const opts2 = page.getByRole('option')
      if (await opts2.count()) await opts2.first().click()
    }
    await page.waitForTimeout(300)
    const placeBtn = page.getByRole('button', { name: 'Place in ledger' })
    if (await placeBtn.count()) {
      await placeBtn.click()
      await page.waitForTimeout(1000)
    } else {
      console.log('no Place in ledger button visible')
      break
    }
  }
  await shot(page, 'r1-ca-review-after-placing')
  console.log('final text:\n', (await page.locator('body').innerText()).slice(0, 1500))
} finally {
  console.log('problems:', problems)
  await close()
}
