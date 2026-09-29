import { signedIn, WEB, SHOTS } from '../lib/session.mjs'
const { page, close } = await signedIn('admin')
const CID = 'd330689c-c0c6-4670-b8e8-69fcae492888'
await page.goto(`${WEB}/clients/${CID}/review`); await page.waitForTimeout(1500)
const sel = async () => page.evaluate(() => document.querySelector('tr[aria-selected=true],tr[data-selected=true]')?.innerText.slice(0,40) ?? [...document.querySelectorAll('tbody tr')].findIndex(r=>r.className.includes('amber')||r.getAttribute('aria-selected')=='true'))
console.log('start', await sel())
for (const k of ['j','ArrowDown','ArrowDown','k']) { await page.locator('body').click({position:{x:700,y:20}}); await page.keyboard.press(k); await page.waitForTimeout(200); console.log(k, await sel()) }
// list inputs w/o accessible names
const inputs = await page.evaluate(() => [...document.querySelectorAll('input,select,textarea')].map(e => ({ t: e.tagName, type: e.type, id: e.id, aria: e.getAttribute('aria-label'), lab: e.labels?.[0]?.innerText?.slice(0,30), role: e.getAttribute('role'), ph: e.placeholder })))
console.log(JSON.stringify(inputs.filter(i=>!i.aria && !i.lab)))
// shortcut help?
await page.keyboard.press('?'); await page.waitForTimeout(400)
await page.screenshot({ path: SHOTS + '/r1-ux-help.png' })
console.log((await page.locator('[role=dialog]').allInnerTexts()).join('|').slice(0,600))
await close()
