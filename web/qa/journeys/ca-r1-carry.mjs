import { signedIn, shot, visibleText } from '../lib/session.mjs'
const { page, problems, close } = await signedIn('admin')
await page.goto('http://127.0.0.1:5173/clients'); await page.waitForTimeout(1500)
// M1-008
await page.getByRole('button',{name:'New client'}).click(); await page.waitForTimeout(500)
await page.getByLabel(/Client name|Name/i).first().fill('QA CA Esc Test'); await page.keyboard.press('Escape'); await page.waitForTimeout(600)
await shot(page,'r1-ca-m1008-esc'); let t=await visibleText(page); console.log('M1-008 after Esc:', /Discard/.test(t)? 'PROMPT SHOWN':'no prompt', '| dialog still open:', /Keep editing/.test(t))
// M1-012
const before = await page.evaluate(()=>document.activeElement?.tagName+':'+(document.activeElement?.textContent||'').slice(0,20))
console.log('focus at prompt', before)
const seq=[]; for (let i=0;i<5;i++){ await page.keyboard.press('Tab'); seq.push(await page.evaluate(()=>{const a=document.activeElement;return (a?.getAttribute('aria-label')||a?.textContent||a?.tagName||'').trim().slice(0,25)})) }
console.log('M1-012 tab sequence', seq)
await page.keyboard.press('Escape'); await page.waitForTimeout(400); t=await visibleText(page); console.log('Esc on prompt: prompt still there?', /Keep editing/.test(t))
await shot(page,'r1-ca-m1012-prompt')
// keep editing then verify text retained
await page.getByRole('button',{name:'Keep editing'}).click(); await page.waitForTimeout(300)
console.log('name retained:', await page.getByLabel(/Client name|Name/i).first().inputValue())
await page.keyboard.press('Escape'); await page.getByRole('button',{name:'Discard'}).click(); await page.waitForTimeout(400)
// M1-011
for (const q of ['dark','zzzq']) {
  await page.keyboard.press('Control+k'); await page.waitForTimeout(400)
  await page.keyboard.type(q); await page.waitForTimeout(150); await page.keyboard.press('Enter'); await page.waitForTimeout(900)
  console.log('M1-011', q, 'url', page.url(), 'dark class:', await page.evaluate(()=>document.documentElement.className+'|'+document.documentElement.dataset.theme))
  await page.keyboard.press('Escape'); await page.goto('http://127.0.0.1:5173/clients'); await page.waitForTimeout(800)
}
// immediate
await page.keyboard.press('Control+k'); await page.waitForTimeout(400); await page.keyboard.type('zzzq'); await page.keyboard.press('Enter'); await page.waitForTimeout(700); console.log('M1-011 immediate zzzq url', page.url())
console.log(problems); await close()
