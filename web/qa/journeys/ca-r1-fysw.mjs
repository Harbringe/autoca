import { signedIn, shot, visibleText } from '../lib/session.mjs'
const CID='73d99780-eca9-48e7-8ab2-a8e1cee1271f'
const { page, problems, close } = await signedIn('admin')
await page.goto(`http://127.0.0.1:5173/clients/${CID}/reports`); await page.waitForTimeout(1200)
await page.getByLabel('Financial year').selectOption({label:'FY 2025-26'}); await page.waitForTimeout(1500)
let t=await visibleText(page); console.log('REPORTS FY25-26:',t.slice(t.indexOf('Print'),t.indexOf('Print')+400))
for (const tab of ['Balance Sheet','Bank Reconciliation']) { await page.getByText(tab,{exact:true}).first().click(); await page.waitForTimeout(1200); t=await visibleText(page); console.log(tab,':',t.slice(t.indexOf('Print'),t.indexOf('Print')+500)) }
await page.goto(`http://127.0.0.1:5173/clients/${CID}/daybook`); await page.waitForTimeout(1500); t=await visibleText(page); console.log('DAYBOOK:', t.slice(t.indexOf('Masters'),t.indexOf('Masters')+300))
await page.goto(`http://127.0.0.1:5173/clients/${CID}`); await page.waitForTimeout(1200); t=await visibleText(page); console.log('OVERVIEW:', t.slice(t.indexOf('Masters'),t.indexOf('Masters')+400))
console.log(problems); await close()
