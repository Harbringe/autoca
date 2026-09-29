// Place the 6 "needs a ledger" rows for QA CA Ashok Enterprises, as staff, through the screen,
// creating one shared ledger for the receipt and one for the payments.
import { signedIn, shot } from '../lib/session.mjs'

const CID = '73d99780-eca9-48e7-8ab2-a8e1cee1271f'
const { page, problems, close } = await signedIn('staff')

async function placeOne(ledgerName, groupName) {
  const ledgerInput = page.getByRole('combobox', { name: /Ledger \(the other side/i }).first()
  await ledgerInput.click()
  await page.waitForTimeout(200)
  await ledgerInput.fill(ledgerName)
  await page.waitForTimeout(500)
  const createOpt = page.locator("[role=listbox] [role=option]", { hasText: "Create ledger" })
  if (await createOpt.count()) {
    await createOpt.click()
    await page.waitForTimeout(400)
    const group = page.getByRole('button', { name: groupName, exact: true })
    if (await group.count()) await group.click()
    await page.waitForTimeout(200)
    await page.getByRole('button', { name: 'Create and use' }).click()
    await page.waitForTimeout(500)
  } else {
    const opt = page.locator("[role=listbox] [role=option]").first()
    await opt.click()
    await page.waitForTimeout(300)
  }
  const placeBtn = page.getByRole('button', { name: 'Place in ledger' })
  await placeBtn.click()
  await page.waitForTimeout(1000)
}

try {
  await page.goto(`http://127.0.0.1:5173/clients/${CID}/review`)
  await page.waitForTimeout(800)

  // Row 1: receipt from MEHTA HARDWARE -> a sundry debtor
  await placeOne('QA CA Mehta Hardware', 'Sundry Debtors')

  // Remaining 5 are all payments (courier/marketplace) -> one indirect-expense ledger
  for (let i = 0; i < 5; i++) {
    const text = await page.locator('body').innerText()
    const m = text.match(/Needs a ledger (\d+)/)
    console.log('remaining needs-a-ledger:', m ? m[1] : '?')
    if (m && m[1] === '0') break
    await placeOne('QA CA Miscellaneous Expenses', 'Indirect Expenses')
  }

  await shot(page, 'r1-ca-review-after-placing2')
  console.log('final text:\n', (await page.locator('body').innerText()).slice(0, 1200))
} finally {
  console.log('problems:', problems)
  await close()
}
