import { signedIn, WEB, SHOTS } from '../lib/session.mjs'
const { page, close } = await signedIn('admin')
const CID = 'd330689c-c0c6-4670-b8e8-69fcae492888'
await page.goto(`${WEB}/clients/${CID}/review`); await page.waitForTimeout(1500)
// tab order first 40 stops with focus ring check
const stops = []
for (let i = 0; i < 45; i++) {
  await page.keyboard.press('Tab')
  stops.push(await page.evaluate(() => {
    const e = document.activeElement; const cs = getComputedStyle(e)
    return { tag: e.tagName, name: (e.getAttribute('aria-label') || e.innerText || e.getAttribute('title') || '').trim().slice(0, 30), outline: cs.outlineStyle + ' ' + cs.outlineWidth + ' ' + cs.outlineColor, shadow: cs.boxShadow.slice(0, 50) }
  }))
}
stops.forEach((s, i) => console.log(i, s.tag, JSON.stringify(s.name), s.outline, s.shadow))
// small targets
const small = await page.evaluate(() => [...document.querySelectorAll('a,button,input,select,[role=button],[role=tab],[role=checkbox]')].map(e => { const r = e.getBoundingClientRect(); return { t: e.tagName, n: (e.getAttribute('aria-label') || e.innerText || e.type || '').trim().slice(0, 25), w: Math.round(r.width), h: Math.round(r.height) } }).filter(x => (x.w < 24 || x.h < 24) && x.w > 0))
console.log('SMALL', JSON.stringify(small))
console.log(await page.locator('main, body').first().ariaSnapshot().then(s => s.slice(0, 3500)))
await close()
