import { signedIn, shot, visibleText } from '../lib/session.mjs'

for (const role of ['staff']) {
  const { page, problems, close } = await signedIn(role)
  await page.goto('http://127.0.0.1:5173/clients/591f73c7-35a5-42cf-9998-b5fc55ca1799/books')
  await page.waitForTimeout(800)
  await shot(page, `sca-r1-books-${role}`)
  console.log(`--- ${role} books ---`)
  console.log(await visibleText(page))
  console.log('problems', problems)
  await close()
}
