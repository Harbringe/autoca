import { signedIn, shot, visibleText } from '../lib/session.mjs'
const CID='8b70e7ab-e10d-40ac-818c-9cdf9112db03'
const { page, problems, close } = await signedIn('admin')
await page.goto(`http://127.0.0.1:5173/clients/${CID}/daybook`); await page.waitForTimeout(1500)
const log=[]; page.on('response',r=>{ if(/\/api\//.test(r.url())&&r.request().method()!=='OPTIONS') log.push(r.status()+' '+r.request().method()+' '+r.url().replace('http://127.0.0.1:5173','').slice(0,110)) })
await page.getByText('Being courier charges').first().click(); await page.waitForTimeout(1200)
console.log('after open:', log.splice(0)); await shot(page,'r1-ca-entry-dialog'); const t=await visibleText(page); console.log(t.slice(t.indexOf('Being courier')-300, t.indexOf('Being courier')+900))
await page.getByRole('button',{name:/Unpost/}).last().click(); await page.waitForTimeout(700); await shot(page,'r1-ca-unpost-confirm'); console.log((await visibleText(page)).slice(-500))
await page.getByRole('button',{name:/Unpost/}).last().click(); await page.waitForTimeout(2500)
console.log('after unpost:', log); console.log(problems); await close()
