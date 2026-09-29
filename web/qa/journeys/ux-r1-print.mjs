import { signedIn, WEB, SHOTS } from '../lib/session.mjs'
const { page, close } = await signedIn('admin')
const CID='d330689c-c0c6-4670-b8e8-69fcae492888'
await page.goto(`${WEB}/clients/${CID}/reports`); await page.getByText('Show FY 2025-26').click(); await page.waitForTimeout(1500)
for (const tab of ['Profit & Loss A/c','Balance Sheet','Bank Reconciliation']) {
  await page.getByRole('tab',{name:tab}).click().catch(()=>page.getByText(tab,{exact:true}).click()); await page.waitForTimeout(1200)
  await page.screenshot({ path: SHOTS + `/r1-ux-rep-${tab.split(' ')[0].toLowerCase()}.png`, fullPage:true })
  console.log('==',tab, page.url()); console.log((await page.locator('main').innerText()).slice(300,1400))
}
await page.getByText('Trial Balance',{exact:true}).first().click(); await page.waitForTimeout(800)
await page.emulateMedia({ media: 'print' }); await page.waitForTimeout(300)
await page.screenshot({ path: SHOTS + '/r1-ux-print.png' })
await page.pdf({ path: SHOTS + '/r1-ux-print.pdf', format: 'A4' })
await close()
