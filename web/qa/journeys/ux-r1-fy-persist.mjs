import { signedIn, shot, visibleText, WEB } from '../lib/session.mjs'
const { page, problems, close } = await signedIn('admin', { width: 1440, height: 900 })
const CID = 'd330689c-c0c6-4670-b8e8-69fcae492888'
await page.goto(`${WEB}/clients/${CID}`)
await page.waitForLoadState('networkidle')
await page.getByRole('button', { name: 'Show FY 2025-26' }).click()
await page.waitForTimeout(500)
console.log('after click, url:', page.url())
console.log('FY select value:', await page.locator('select, [role=combobox]').first().innerText().catch(()=>'n/a'))
// now go to Statements tab
await page.getByRole('link', { name: 'Statements' }).click()
await page.waitForLoadState('networkidle')
await page.waitForTimeout(400)
console.log('Statements url:', page.url())
const txt = await visibleText(page)
console.log(txt.includes('You are looking at FY 2026-27') ? 'MISMATCH BANNER STILL SHOWING ON STATEMENTS' : 'banner gone / fy persisted')
console.log(txt.slice(0, 600))
await close()
