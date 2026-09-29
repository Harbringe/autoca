import { chromium } from '@playwright/test'
import { WEB, SHOTS } from '../lib/session.mjs'
const b = await chromium.launch()
const page = await (await b.newContext({ viewport: { width: 1280, height: 800 } })).newPage()
await page.goto(WEB + '/'); await page.waitForTimeout(800)
await page.screenshot({ path: SHOTS + '/r1-ux-signin.png' })
console.log(await page.locator('body').ariaSnapshot())
console.log('title', await page.title(), 'lang', await page.evaluate(()=>document.documentElement.lang))
// submit empty
// pw type + autocomplete
console.log(await page.evaluate(()=>[...document.querySelectorAll('input')].map(i=>[i.type,i.autocomplete,i.name])))
// reflow at 400% (320 css px)
await page.setViewportSize({width:320,height:600}); await page.waitForTimeout(300)
console.log('320 scrollW', await page.evaluate(()=>document.documentElement.scrollWidth))
// offline
await page.setViewportSize({width:1280,height:800})
await page.context().setOffline(true)
await page.getByLabel('Email').fill('qa.admin@autoca.test'); await page.getByLabel('Password').fill('x'); await page.getByRole('button',{name:'Sign in'}).click(); await page.waitForTimeout(12000)
await page.screenshot({ path: SHOTS + '/r1-ux-signin-offline.png' })
console.log('OFFLINE:', (await page.locator('body').innerText()).slice(0,300))
await b.close()
