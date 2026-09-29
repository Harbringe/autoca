import { signedIn, WEB, SHOTS } from '../lib/session.mjs'
const { page, close, problems } = await signedIn('admin')
const CID='052ec4a5-272c-412e-a36e-06ca5540cf54'
await page.goto(`${WEB}/clients/${CID}/review?stage=pending_approval`); await page.locator('tbody tr').first().waitFor(); await page.waitForTimeout(1200)
const sel = () => page.evaluate(()=>{const r=[...document.querySelectorAll('tbody tr')]; const i=r.findIndex(x=>x.getAttribute('aria-selected')=='true'); return [i, r.length, r[i]?.innerText.replace(/\s+/g,' ').slice(0,50)]})
console.log('before', await sel(), 'tab title', await page.title())
await page.locator('body').click({position:{x:700,y:20}})
await page.keyboard.press('p'); await page.waitForTimeout(150); await page.keyboard.press('p'); 
for (const t of [100,600,1500,4000,7000]) { await page.waitForTimeout(t===100?100:t-(t/2)); console.log(t,'toasts', await page.locator('[role=status],li[data-sonner-toast],[data-radix-toast-root]').allInnerTexts(), await sel()) }
await page.screenshot({ path: SHOTS + '/r1-ux-after-post.png' })
console.log('badge', await page.getByRole('link',{name:/^Review/}).innerText())
console.log(problems)
await close()
