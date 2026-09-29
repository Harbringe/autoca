import { signedIn, shot, visibleText } from '../lib/session.mjs'
const CID='8b70e7ab-e10d-40ac-818c-9cdf9112db03'
const { page, problems, close } = await signedIn('admin')
await page.goto(`http://127.0.0.1:5173/clients/${CID}/masters`); await page.waitForTimeout(1200)
await page.getByRole('tab',{name:'Parties'}).or(page.getByText('Parties',{exact:true})).first().click(); await page.waitForTimeout(800)
let t=await visibleText(page); console.log(t.slice(t.indexOf('Parties')))
await page.getByRole('button',{name:/New party/}).click(); await page.waitForTimeout(500)
console.log(await page.locator('[role=dialog]').innerText())
await page.getByLabel(/Name/).first().fill('QA CA Test Party'); 
const g=page.getByLabel(/GSTIN/i); await g.fill('27AAAAA0000A1Z6'); await page.keyboard.press('Tab'); await page.waitForTimeout(400)
console.log('BAD GSTIN dialog:', await page.locator('[role=dialog]').innerText())
await shot(page,'r1-ca-party-badgstin')
await g.fill('27aabcu9603r1zx'); await page.keyboard.press('Tab'); await page.waitForTimeout(400)
console.log('LOWER dialog:', (await page.locator('[role=dialog]').innerText()).slice(0,500))

await g.fill('27AAAAA0000A1Z6'); await page.getByRole('button',{name:'Save'}).click(); await page.waitForTimeout(1200)
console.log('SAVE BAD:', (await page.locator('[role=dialog]').innerText()).slice(0,400)); await shot(page,'r1-ca-party-badsave')
console.log(problems); await close()
