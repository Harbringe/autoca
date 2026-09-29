import { chromium } from '@playwright/test'
import { WEB, PEOPLE, PASSWORD, SHOTS } from '../lib/session.mjs'
const b = await chromium.launch()
const ctx = await b.newContext({ viewport: { width: 390, height: 800 }, locale: 'en-IN', hasTouch: true, isMobile: true })
const page = await ctx.newPage()
await page.goto(WEB + '/'); await page.getByLabel('Email').fill(PEOPLE.admin); await page.getByLabel('Password').fill(PASSWORD)
await page.getByRole('button', { name: 'Sign in' }).click(); await page.waitForTimeout(3000)
const CID = 'd330689c-c0c6-4670-b8e8-69fcae492888'
await page.goto(`${WEB}/clients/${CID}/review`); await page.getByText('Ready to post').first().waitFor(); await page.waitForTimeout(1200)
const sc = await page.evaluate(() => { const t=document.querySelector('table'); let e=t; while(e && e.scrollWidth<=e.clientWidth) e=e.parentElement; return e?[e.tagName,e.scrollWidth,e.clientWidth]:null })
console.log('table scroller', sc)
// tap a row: does the decision panel show?
await page.locator('tbody tr').nth(1).click(); await page.waitForTimeout(800)
await page.screenshot({ path: SHOTS + '/r1-ux-m-review-tap.png' })
console.log('scrollY', await page.evaluate(()=>scrollY), 'dialog?', await page.locator('[role=dialog]').count())
console.log(await page.evaluate(()=>[...document.querySelectorAll('button,a')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&r.height&&(r.height<44||r.width<44)}).length), 'targets <44px')
await page.getByRole('button',{name:/menu|navigation/i}).first().click().catch(()=>console.log('no menu btn')); await page.waitForTimeout(500)
await page.screenshot({ path: SHOTS + '/r1-ux-m-menu.png' })
const pos = await page.evaluate(()=>{const e=[...document.querySelectorAll('button')].find(b=>/Post entry|Place in ledger|Confirm ledger/.test(b.innerText)); return e?[Math.round(e.getBoundingClientRect().top+scrollY), document.body.scrollHeight]:null}); console.log('action btn y / page h', pos)
await b.close()
