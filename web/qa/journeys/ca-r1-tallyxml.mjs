import { signedIn, shot, visibleText } from '../lib/session.mjs'
import fs from 'node:fs'
const CID=process.argv[2]
const { page, problems, close } = await signedIn('admin')
await page.goto(`http://127.0.0.1:5173/clients/${CID}/statements`); await page.waitForTimeout(1500)
const [dl]=await Promise.all([page.waitForEvent('download',{timeout:20000}), page.getByText('Tally XML').first().click()])
console.log('file', dl.suggestedFilename()); const p=await dl.path(); const x=fs.readFileSync(p,'utf8'); console.log(x.length); fs.writeFileSync('qa/samples/ca-r1-tally.xml',x)
console.log(x.slice(0,2500)); console.log('VOUCHERS', (x.match(/<VOUCHER /g)||[]).length)
console.log(problems); await close()
