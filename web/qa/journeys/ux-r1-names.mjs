import { signedIn, WEB } from '../lib/session.mjs'
const { page, close } = await signedIn('admin')
const CID = 'd330689c-c0c6-4670-b8e8-69fcae492888'
for (const [n,u,pre] of [['masters ledgers',`/clients/${CID}/masters`],['rules',`/clients/${CID}/masters?tab=rules`],['statements',`/clients/${CID}/statements`],['daybook',`/clients/${CID}/daybook?fy=2025-26`]]) {
  await page.goto(WEB+u); await page.waitForTimeout(1500)
  if (n==='rules') await page.getByText('Rules',{exact:true}).first().click()
  await page.waitForTimeout(500)
  const names = await page.locator('main a, main button, main input, main select').evaluateAll(els=>els.map(e=>{const nm=(e.getAttribute('aria-label')||e.innerText||'').trim(); return e.tagName+':'+(nm||'(none)')+(e.type==='checkbox'?'':'')}))
  const c={}; names.forEach(x=>c[x]=(c[x]||0)+1)
  console.log('==',n, JSON.stringify(Object.entries(c).filter(([k,v])=>v>1||k.includes('(none)'))))
}
await close()
