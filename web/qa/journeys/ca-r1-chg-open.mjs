import { signedIn, shot, visibleText, apiJson } from '../lib/session.mjs'
const CID='73d99780-eca9-48e7-8ab2-a8e1cee1271f'
const { page, problems, close } = await signedIn('staff')
const tb=async()=>{const j=await apiJson(page,`/api/v1/clients/${CID}/reports/trial-balance/`);return j.rows[0].opening_display+' / closing '+j.rows[0].closing_debit_display}
console.log('before',await tb())
await page.goto(`http://127.0.0.1:5173/clients/${CID}/statements`); await page.waitForTimeout(1200)
await page.getByRole('button',{name:'Change opening'}).click(); await page.waitForTimeout(500)
await shot(page,'r1-ca-chg-open-dialog'); console.log((await visibleText(page)).slice(-600))
const inp=page.getByRole('textbox',{name:/Opening balance/}); await inp.fill('125000'); 
await page.getByRole('button',{name:'Confirm opening balance'}).click(); await page.waitForTimeout(1500)
console.log((await visibleText(page)).slice(-300)); console.log('after',await tb())
console.log(problems); await close()
