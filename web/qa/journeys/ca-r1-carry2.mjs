import { signedIn, shot, visibleText } from '../lib/session.mjs'
const { page, problems, close } = await signedIn('admin')
await page.goto('http://127.0.0.1:5173/clients'); await page.waitForTimeout(1500)
await page.getByRole('button',{name:'New client'}).click(); await page.waitForTimeout(500)
await page.getByLabel(/Client name|Name/i).first().fill('QA CA Esc Test'); await page.keyboard.press('Escape'); await page.waitForTimeout(600)
const act=()=>page.evaluate(()=>{const a=document.activeElement;return a.tagName+' "'+(a.getAttribute('aria-label')||a.textContent||'').trim().slice(0,25)+'" inPrompt='+!!a.closest('[role=alertdialog]')})
console.log('start', await act())
for (let i=0;i<4;i++){ await page.keyboard.press('Tab'); console.log('tab',i+1, await act(), '| prompt visible:', /Keep editing/.test(await visibleText(page))) }
await shot(page,'r1-ca-m1012-after-tabs')
console.log(problems); await close()
