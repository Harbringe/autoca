import { signedIn, shot, visibleText } from '../lib/session.mjs'
const CID='8b70e7ab-e10d-40ac-818c-9cdf9112db03'
const { page, problems, close } = await signedIn('admin')
await page.goto(`http://127.0.0.1:5173/clients/${CID}/books`); await page.waitForTimeout(1200)
await page.getByRole('button',{name:'Send for review'}).click(); await page.waitForTimeout(500)
await page.getByRole('button',{name:'Send for review'}).last().click(); await page.waitForTimeout(2000)
const t=await visibleText(page); console.log(t.slice(t.indexOf('Masters'),t.indexOf('Masters')+700)); await shot(page,'r1-ca-resend-after-signoff')
console.log(problems); await close()
