import { signedIn, shot, visibleText } from '../lib/session.mjs'
const CID='8b70e7ab-e10d-40ac-818c-9cdf9112db03'
const { page, problems, close } = await signedIn('admin')
await page.goto(`http://127.0.0.1:5173/clients/${CID}/review`); await page.waitForTimeout(1500)
let t=await visibleText(page); console.log(t.slice(t.indexOf('Masters'),t.indexOf('Masters')+500))
await page.getByRole('button',{name:/Post all high-confidence/}).click().catch(e=>console.log('no post all button')); await page.waitForTimeout(600)
const b=page.getByRole('button',{name:/^Post \d+$/}); if (await b.count()) { await b.click(); await page.waitForTimeout(3000) }
t=await visibleText(page); console.log(t.slice(t.indexOf('Masters'),t.indexOf('Masters')+700)); await shot(page,'r1-ca-locked-post')
console.log(problems); await close()
