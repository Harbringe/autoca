// Screenshots of the navigation (rail, client panel, drawer, switcher) against the mock API.
//   node qa/tools/nav-shots.mjs <output folder>
import { createRequire } from 'node:module'
import fs from 'node:fs'
const require = createRequire(import.meta.url)
const { chromium } = require('playwright')
const OUT = process.argv[2]
fs.mkdirSync(OUT, { recursive: true })
const C = 'c0000000-0000-4000-8000-000000000001'
const WEB = 'http://localhost:5173'
const sizes = [[1440, 900], [1024, 768], [768, 1024], [360, 740]]
const browser = await chromium.launch()
const problems = []
for (const dark of [false, true]) for (const [w, h] of sizes) for (const scope of ['firm', 'client']) for (const extra of ['', 'drawer', 'switcher']) {
  if (extra === 'drawer' && w >= 1024) continue
  if (extra === 'switcher' && scope === 'firm') continue
  if (extra === 'switcher' && w < 1024 && w !== 360) continue
  const name = `${w}-${scope}${extra ? '-' + extra : ''}-${dark ? 'dark' : 'light'}`
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, colorScheme: dark ? 'dark' : 'light' })
  await ctx.addInitScript((d) => { try { localStorage.setItem('autoca.theme', d ? 'dark' : 'light') } catch {} }, dark)
  const page = await ctx.newPage()
  page.on('pageerror', (e) => problems.push(`${name}: ${e.message}`))
  await page.goto(WEB + (scope === 'client' ? `/clients/${C}/ledgers` : '/alerts'), { waitUntil: 'networkidle' })
  await page.waitForTimeout(500)
  try {
    if (extra === 'drawer') await page.getByRole('button', { name: 'Open menu' }).click()
    if (extra === 'switcher') await page.getByRole('button', { name: /Switch client/ }).first().click()
    await page.waitForTimeout(400)
  } catch (e) { problems.push(`${name}: ${String(e.message).split('\n')[0]}`) }
  const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  if (over > 0) problems.push(`${name}: ${over}px wider than window`)
  await page.screenshot({ path: `${OUT}/${name}.png` })
  await ctx.close()
}
await browser.close()
console.log(problems.join('\n') || 'no problems')
