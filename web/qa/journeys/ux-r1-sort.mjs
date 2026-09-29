import { signedIn, WEB } from '../lib/session.mjs'
const { page, close } = await signedIn('admin')
const CID='d330689c-c0c6-4670-b8e8-69fcae492888'
await page.goto(`${WEB}/clients/${CID}/review`); await page.locator('tbody tr').first().waitFor(); await page.waitForTimeout(800)
const first=()=>page.locator('tbody tr').first().innerText()
const a=await first(); await page.getByRole('columnheader',{name:'Date'}).click(); await page.waitForTimeout(500); const b=await first()
await page.getByRole('columnheader',{name:'Deposit'}).click(); await page.waitForTimeout(500); const c=await first()
console.log(a.replace(/\s+/g,' ').slice(0,40),'|',b.replace(/\s+/g,' ').slice(0,40),'|',c.replace(/\s+/g,' ').slice(0,40))
console.log('search inputs', await page.locator('input[type=search],input[placeholder*=earch]').count(), 'sortable attr', await page.locator('th[aria-sort]').count())
await close()
