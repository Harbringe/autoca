import { signedIn, shot, visibleText } from '../lib/session.mjs'
const CID='8b70e7ab-e10d-40ac-818c-9cdf9112db03'
const { page, problems, close } = await signedIn('admin')
await page.goto(`http://127.0.0.1:5173/clients/${CID}/books`); await page.waitForTimeout(1500)
await page.getByRole('button',{name:'Sign off the books'}).click(); await page.waitForTimeout(600)
await page.getByRole('button',{name:'Sign off',exact:true}).click(); await page.waitForTimeout(2500)
const t=await visibleText(page); console.log(t.slice(t.indexOf('Masters'),t.indexOf('Masters')+900)); await shot(page,'r1-ca-bindal-signed')
console.log(problems); await close()
