import { signedIn, shot, visibleText } from '../lib/session.mjs'
const CID='8b70e7ab-e10d-40ac-818c-9cdf9112db03'
const { page, problems, close } = await signedIn('admin')
await page.goto(`http://127.0.0.1:5173/clients/${CID}/review`); await page.waitForTimeout(1500)
let t=await visibleText(page); console.log(t.slice(t.indexOf('Needs a ledger'),t.indexOf('Needs a ledger')+700))
await shot(page,'r1-ca-review-after-unpost')
await page.getByText('BLUE DART').first().click(); await page.waitForTimeout(500)
await page.getByRole('button',{name:'Post entry'}).click(); await page.waitForTimeout(2000)
t=await visibleText(page); console.log(t.slice(t.indexOf('Needs a ledger'),t.indexOf('Needs a ledger')+400))
console.log(problems); await close()
