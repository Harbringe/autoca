import { signedIn, shot, visibleText } from '../lib/session.mjs'
const { page, problems, close } = await signedIn('admin')
await page.goto('http://127.0.0.1:5173/clients'); await page.waitForTimeout(1200)
await page.getByText('AA',{exact:true}).first().click(); await page.waitForTimeout(500)
console.log('AVATAR:', await page.locator('[role=menu]').innerText().catch(()=>'no menu')); await shot(page,'r1-ca-avatar-menu')
await page.keyboard.press('Escape')
await page.getByText('QA Associates (synthetic)').first().click({timeout:3000}).catch(()=>console.log('footer not clickable'))
await page.waitForTimeout(600); console.log(page.url()); console.log((await visibleText(page)).slice(0,300)); await shot(page,'r1-ca-footer-click')
console.log(problems); await close()
