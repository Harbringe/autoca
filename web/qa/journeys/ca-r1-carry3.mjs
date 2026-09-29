import { signedIn, shot, visibleText } from '../lib/session.mjs'
const { page, problems, close } = await signedIn('admin')
await page.goto('http://127.0.0.1:5173/clients'); await page.waitForTimeout(1500)
const th=()=>page.evaluate(()=>document.documentElement.className+'|'+document.documentElement.dataset.theme)
console.log('theme0', await th())
for (const [q,wait] of [['dark',600],['zzzq',600],['all',600],['dark',0],['zzzq',0]]) {
  await page.goto('http://127.0.0.1:5173/clients'); await page.waitForTimeout(1000)
  await page.keyboard.press('Control+k'); await page.waitForTimeout(500)
  await page.keyboard.type(q); await page.waitForTimeout(wait);
  if (q==='dark'&&wait===600) await shot(page,'r1-ca-pal-dark')
  await page.keyboard.press('Enter'); await page.waitForTimeout(1000)
  console.log('M1-011', q, wait, 'url', page.url().replace('http://127.0.0.1:5173',''), 'theme', await th())
}
console.log(problems); await close()
