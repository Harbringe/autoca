import { signedIn, shot, visibleText } from '../lib/session.mjs'
const CID='8b70e7ab-e10d-40ac-818c-9cdf9112db03'
const { page, problems, close } = await signedIn('admin')
await page.goto(`http://127.0.0.1:5173/clients/${CID}/books`); await page.waitForTimeout(1500)
let t=await visibleText(page); console.log(t.slice(t.indexOf('Masters')))
console.log(await page.getByRole('button').allInnerTexts())
await page.getByRole('button',{name:'Send for review'}).click(); await page.waitForTimeout(700); await shot(page,'r1-ca-send-review-dialog'); t=await visibleText(page); console.log('DIALOG',t.slice(-900))

await page.getByRole('button',{name:'Send for review'}).last().click(); await page.waitForTimeout(2000)
t=await visibleText(page); console.log('AFTER SEND',t.slice(t.indexOf('Masters'),t.indexOf('Masters')+900)); console.log(await page.getByRole('button').allInnerTexts())
await shot(page,'r1-ca-after-send')
const so=page.getByRole('button',{name:/Sign off/}).first(); if (await so.count()) { await so.click(); await page.waitForTimeout(800); await shot(page,'r1-ca-signoff-dialog'); t=await visibleText(page); console.log('SIGNOFF DIALOG',t.slice(-1100)) }
console.log(problems); await close()
