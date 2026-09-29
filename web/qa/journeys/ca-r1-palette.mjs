import { signedIn, shot, visibleText } from '../lib/session.mjs'
const [role,path]=process.argv.slice(2)
const { page, problems, close } = await signedIn(role)
await page.goto('http://127.0.0.1:5173/'+path); await page.waitForTimeout(1500)
await page.keyboard.press('Control+k'); await page.waitForTimeout(800)
await shot(page,'r1-ca-palette-'+role); console.log(await page.locator('[role=dialog]').first().innerText())
await page.keyboard.press('Escape'); await page.keyboard.press('?'); await page.waitForTimeout(600); console.log('---- ?'); console.log(await page.locator('[role=dialog]').first().innerText().catch(()=>'no dialog'))
console.log(problems); await close()
