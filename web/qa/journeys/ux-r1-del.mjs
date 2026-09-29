import { signedIn, WEB, SHOTS } from '../lib/session.mjs'
const { page, close } = await signedIn('admin')
const CID='052ec4a5-272c-412e-a36e-06ca5540cf54'
const titles=[]
for (const p of ['/clients','/clients/'+CID,'/clients/'+CID+'/review','/clients/'+CID+'/reports']) { await page.goto(WEB+p); await page.waitForTimeout(1000); titles.push(await page.title()) }
console.log('titles', titles)
await page.goto(`${WEB}/clients/${CID}/statements`); await page.getByText('Statements on file').waitFor()
await page.getByRole('button',{name:'Remove statement'}).click(); await page.waitForTimeout(600)
await page.screenshot({ path: SHOTS + '/r1-ux-remove-stmt.png' })
console.log(await page.locator('[role=dialog],[role=alertdialog]').allInnerTexts())
await page.keyboard.press('Escape')
await close()
