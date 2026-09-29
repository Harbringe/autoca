import { signedIn, shot, visibleText } from '../lib/session.mjs'
const CID='8b70e7ab-e10d-40ac-818c-9cdf9112db03'
const { page, problems, close } = await signedIn('admin')
await page.goto(`http://127.0.0.1:5173/clients/${CID}/statements`); await page.waitForTimeout(1200)
await page.getByRole('button',{name:'Confirm opening'}).click(); await page.waitForTimeout(600)
await shot(page,'r1-ca-bindal-open-dialog'); const t=await visibleText(page); console.log(t.slice(t.indexOf('Statements on file')))

await page.getByRole('button',{name:'Confirm opening balance'}).click(); await page.waitForTimeout(2000)
const t2=await visibleText(page); console.log(t2.slice(t2.indexOf('Bank accounts')))
console.log(problems); await close()
