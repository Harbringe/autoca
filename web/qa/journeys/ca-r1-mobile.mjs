import { signedIn, shot, visibleText } from '../lib/session.mjs'
const CID='8b70e7ab-e10d-40ac-818c-9cdf9112db03'
const { page, problems, close } = await signedIn('admin')
await page.setViewportSize({width:390,height:800})
for (const p of ['','/review','/daybook','/reports','/books']) {
  await page.goto(`http://127.0.0.1:5173/clients/${CID}${p}`); await page.waitForTimeout(1500)
  const ov = await page.evaluate(()=>({sw:document.documentElement.scrollWidth,cw:document.documentElement.clientWidth}))
  console.log(p||'/', JSON.stringify(ov)); await shot(page,'r1-ca-m390'+p.replace('/','-'))
}
console.log(problems); await close()
