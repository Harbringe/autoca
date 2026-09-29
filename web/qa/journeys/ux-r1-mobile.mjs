import { chromium } from '@playwright/test'
import { WEB, PEOPLE, PASSWORD, SHOTS } from '../lib/session.mjs'
const b = await chromium.launch()
const ctx = await b.newContext({ viewport: { width: 390, height: 800 }, locale: 'en-IN' })
const page = await ctx.newPage()
await page.goto(WEB + '/')
await page.screenshot({ path: SHOTS + '/r1-ux-m-login.png' })
await page.getByLabel('Email').fill(PEOPLE.admin)
await page.getByLabel('Password').fill(PASSWORD)
await page.getByRole('button', { name: 'Sign in' }).click()
await page.waitForTimeout(3000)
await page.screenshot({ path: SHOTS + '/r1-ux-m-after-login.png' })
console.log(await page.locator('body').innerText())
console.log('scrollW', await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth]))
const CID = 'd330689c-c0c6-4670-b8e8-69fcae492888'
for (const [n, p] of [['clients','/clients'],['overview',`/clients/${CID}`],['review',`/clients/${CID}/review`],['daybook',`/clients/${CID}/daybook`],['reports',`/clients/${CID}/reports`],['books',`/clients/${CID}/books`],['masters',`/clients/${CID}/masters`]]) {
  await page.goto(WEB + p); await page.waitForTimeout(1500)
  console.log(n, await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth]))
  await page.screenshot({ path: `${SHOTS}/r1-ux-m-${n}.png` })
}
await b.close()
