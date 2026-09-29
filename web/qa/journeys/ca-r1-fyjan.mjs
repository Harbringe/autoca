import { signedIn, shot, visibleText } from '../lib/session.mjs'
const { page, problems, close } = await signedIn('admin')
await page.goto('http://127.0.0.1:5173/clients'); await page.waitForTimeout(1200)
await page.getByRole('button', { name: 'New client' }).click(); await page.waitForTimeout(300)
await page.getByLabel('Client name').fill('QA CA FY Probe Jan')
console.log('default FY value:', await page.getByLabel('Financial year starts').inputValue())
await page.getByLabel('Financial year starts').fill('01-01-2026'); await page.getByRole('button', { name: 'Add client' }).click(); await page.waitForTimeout(2000)
console.log(page.url()); console.log((await visibleText(page)).slice(300,900))
console.log(problems); await close()
