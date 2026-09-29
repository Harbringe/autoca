import { signedIn, shot, visibleText } from '../lib/session.mjs'
const [role,CID]=process.argv.slice(2)
const { page, problems, close } = await signedIn(role)
await page.goto(`http://127.0.0.1:5173/clients/${CID}/reports`); await page.waitForTimeout(1500)
for (const t of ['Trial Balance','Profit & Loss A/c','Balance Sheet','Bank Reconciliation']) {
  await page.getByRole('tab',{name:t}).or(page.getByRole('button',{name:t})).or(page.getByText(t,{exact:true})).first().click(); await page.waitForTimeout(1500)
  const txt=await visibleText(page); console.log('=====',t); console.log(txt.slice(txt.indexOf('Print')))
  await shot(page,'r1-ca-rep-'+role+'-'+t.replace(/\W/g,''))
}
console.log(problems); await close()
