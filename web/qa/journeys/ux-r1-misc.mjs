import { signedIn, WEB, SHOTS } from '../lib/session.mjs'
const { page, close, problems } = await signedIn('admin')
const CID = 'd330689c-c0c6-4670-b8e8-69fcae492888'
await page.goto(`${WEB}/clients/${CID}/masters`); await page.getByText('Ledgers').first().waitFor()
for (const t of ['Parties','Rules']) { await page.getByRole('tab',{name:t}).click().catch(()=>page.getByText(t,{exact:true}).first().click()); await page.waitForTimeout(900); await page.screenshot({ path: SHOTS + `/r1-ux-masters-${t}.png`, fullPage:true }); console.log('==',t, (await page.locator('main').innerText()).slice(250,900)) }
await page.locator('button:has-text("AA")').click(); await page.waitForTimeout(500)
await page.screenshot({ path: SHOTS + '/r1-ux-avatar.png' })
console.log('AVATAR', await page.locator('[role=menu]').innerText())
await page.keyboard.press('Escape')
await page.goto(`${WEB}/nope-404`); await page.waitForTimeout(800); await page.screenshot({ path: SHOTS + '/r1-ux-404.png' }); console.log('404:', (await page.locator('body').innerText()).slice(0,200))
await page.goto(`${WEB}/clients/00000000-0000-0000-0000-000000000000`); await page.waitForTimeout(1500); await page.screenshot({ path: SHOTS + '/r1-ux-badclient.png' }); console.log('BADCLIENT:', (await page.locator('body').innerText()).slice(0,300))
console.log(problems)
await close()
