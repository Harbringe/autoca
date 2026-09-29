import { signedIn, WEB, SHOTS } from '../lib/session.mjs'
const { page, close } = await signedIn('admin', { width: 1280, height: 800 })
const CID = 'd330689c-c0c6-4670-b8e8-69fcae492888'
await page.emulateMedia({ reducedMotion: 'reduce' })
await page.goto(`${WEB}/clients/${CID}/review`); await page.getByText('Ready to post').first().waitFor()
await page.getByRole('button',{name:'Upload bank statement'}).click(); await page.waitForTimeout(50)
console.log('dialog anim (reduce):', await page.evaluate(()=>{const d=document.querySelector('[role=dialog]'); const cs=getComputedStyle(d); return [cs.animationName,cs.animationDuration,cs.transitionDuration]}))
const spin = await page.evaluate(()=>document.getAnimations().map(a=>a.animationName||a.transitionProperty).slice(0,5)); console.log('running anims', spin)
await page.keyboard.press('Escape')
// 200% zoom equivalent: 640x400 viewport with deviceScaleFactor irrelevant; use 640 css px wide
await page.setViewportSize({ width: 640, height: 450 }); await page.waitForTimeout(500)
await page.screenshot({ path: SHOTS + '/r1-ux-zoom200.png' })
console.log('640 scrollW', await page.evaluate(()=>[document.documentElement.scrollWidth, innerWidth]))
await page.setViewportSize({ width: 320, height: 256 }); await page.waitForTimeout(500)
await page.screenshot({ path: SHOTS + '/r1-ux-zoom400.png' })
console.log('320 scrollW', await page.evaluate(()=>[document.documentElement.scrollWidth, innerWidth]))
await close()
