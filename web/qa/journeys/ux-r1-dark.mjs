import { signedIn, shot, visibleText, WEB } from '../lib/session.mjs'
const { page, problems, close } = await signedIn('admin', { width: 1440, height: 900, dark: true })
const CID = 'd330689c-c0c6-4670-b8e8-69fcae492888'
await page.goto(`${WEB}/clients/${CID}/review`)
await page.waitForTimeout(2000)
console.log(await shot(page, 'r1-ux-review-dark'))
console.log('PROBLEMS:', problems.join('\n')||'none')
await close()
