import { signedIn, shot, visibleText } from '../lib/session.mjs'
const { page, problems, close } = await signedIn('admin')
await page.goto('http://127.0.0.1:5173/clients'); await page.waitForTimeout(1500)
const open=async()=>{ await page.getByRole('button',{name:'New client'}).click(); await page.waitForTimeout(400); await page.getByLabel('Client name').fill('QA CA Esc Test'); await page.keyboard.press('Escape'); await page.waitForTimeout(500) }
await open()
// Esc on prompt keeps name?
await page.keyboard.press('Escape'); await page.waitForTimeout(400)
console.log('after Esc on prompt: dialog open?', await page.locator('[role=dialog]').count(), 'name:', await page.getByLabel('Client name').inputValue().catch(()=>'(gone)'))
await page.keyboard.press('Escape'); await page.waitForTimeout(500)
// Tab twice to Close then Enter
await page.keyboard.press('Tab'); await page.keyboard.press('Tab'); 
console.log('focus', await page.evaluate(()=>document.activeElement.getAttribute('aria-label')||document.activeElement.textContent))
await page.keyboard.press('Enter'); await page.waitForTimeout(600)
const t=await visibleText(page); console.log('after Enter on Close: prompt?', /Keep editing/.test(t), 'dialog open?', await page.locator('[role=dialog]').count(), 'name:', await page.getByLabel('Client name').inputValue().catch(()=>'(gone)'))
await shot(page,'r1-ca-m1012-enter-close')
console.log(problems); await close()
