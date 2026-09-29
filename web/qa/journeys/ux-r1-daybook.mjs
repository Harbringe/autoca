import { signedIn, WEB, SHOTS } from '../lib/session.mjs'
const { page, close, problems } = await signedIn('admin')
const CID='d330689c-c0c6-4670-b8e8-69fcae492888'
await page.goto(`${WEB}/clients/${CID}/daybook`); await page.getByText('Show FY 2025-26').click(); await page.waitForTimeout(1500)
await page.screenshot({ path: SHOTS + '/r1-ux-daybook-fy25.png', fullPage:true })
console.log((await page.locator('main').innerText()).slice(0,1500))
for (const t of ['reports','books']) { await page.goto(`${WEB}/clients/${CID}/${t}`); await page.waitForTimeout(1500); await page.screenshot({ path: SHOTS + `/r1-ux-${t}-fy25.png`, fullPage:true }) }
console.log(problems)
await close()
