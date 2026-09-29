import { signedIn, visibleText, shot } from '../lib/session.mjs'
const role = process.argv[2] || 'admin'
const CID='73d99780-eca9-48e7-8ab2-a8e1cee1271f'
const { page, problems, close } = await signedIn(role)
for (const p of (process.argv[3]||'').split(',')) {
  await page.goto(`http://127.0.0.1:5173/${p.replace('CID',CID)}`); await page.waitForTimeout(2000)
  console.log('=====',p, page.url()); console.log((await visibleText(page)).slice(0,4000))
  await shot(page,'r1-ca-t-'+role+'-'+p.replace(/[^a-z]/gi,'_').slice(-30))
}
console.log('problems',problems); await close()
