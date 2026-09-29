import { signedIn, shot, visibleText } from '../lib/session.mjs'
const [role,CID]=process.argv.slice(2)
const { page, problems, close } = await signedIn(role)
await page.goto(`http://127.0.0.1:5173/clients/${CID}/reports`); await page.waitForTimeout(1500)
await page.getByText('Bank Reconciliation',{exact:true}).first().click(); await page.waitForTimeout(2000)
const txt=await visibleText(page); console.log(txt.slice(txt.indexOf('Masters')))
await shot(page,'r1-ca-bankrec-'+role)
console.log(problems); await close()
