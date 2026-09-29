import { signedIn, shot, visibleText, apiJson } from '../lib/session.mjs'
const CID='8b70e7ab-e10d-40ac-818c-9cdf9112db03'
const { page, problems, close } = await signedIn('admin')
await page.goto(`http://127.0.0.1:5173/clients/${CID}/review`); await page.waitForTimeout(1500)
await page.getByText('MEHTA HARDWARE').first().click(); await page.waitForTimeout(500)
const inp = page.getByRole('combobox', { name: /Ledger \(the other side/i }).first()
await inp.click(); await inp.fill('QA CA Mehta Hardware'); await page.waitForTimeout(600)
await shot(page,'r1-ca-ledgerpicker-typed')
await page.locator('[role=listbox] [role=option]', { hasText: 'Create ledger' }).click(); await page.waitForTimeout(500)
await shot(page,'r1-ca-create-ledger-dialog'); console.log((await visibleText(page)).slice(-1200))

await page.locator('select').filter({ hasText: 'Sundry Debtors' }).first().selectOption({ label: 'Sundry Debtors' })
await page.getByRole('button', { name: 'Create and use' }).click(); await page.waitForTimeout(800)
console.log((await visibleText(page)).slice(-1500))
await shot(page,'r1-ca-after-create-use')
console.log(problems); await close()
