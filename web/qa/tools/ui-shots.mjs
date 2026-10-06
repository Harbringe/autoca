// Screenshots of the real web app against qa/tools/mock-api.mjs, at phone, tablet and desktop widths, light and dark.
//
//   node qa/tools/mock-api.mjs &   npm run dev &   node qa/tools/ui-shots.mjs <output folder>
//
// Prints any page error, console error or sideways overflow it finds.
import { createRequire } from 'node:module'
import fs from 'node:fs'
const require = createRequire(import.meta.url)
const { chromium } = require('playwright')

const OUT = process.argv[2]
fs.mkdirSync(OUT, { recursive: true })
const CLIENT = 'c0000000-0000-4000-8000-000000000001'
const WEB = 'http://127.0.0.1:5173'

const shots = [
  // name, path, width, height, dark, action
  ['01-dash-desktop-light', '/dashboard', 1440, 900, false, null],
  ['02-bell-open-desktop-dark', '/dashboard', 1440, 900, true, async (p) => { await p.getByRole('button', { name: /Alerts:/ }).click() }],
  ['03-client-bookkeeping-desktop-dark', `/clients/${CLIENT}/bookkeeping`, 1440, 900, true, null],
  ['04-view-alerts-open-desktop-dark', `/clients/${CLIENT}/bookkeeping`, 1440, 900, true, async (p) => { await p.getByRole('button', { name: /View alerts/ }).click() }],
  ['05-client-tablet-light', `/clients/${CLIENT}/bookkeeping`, 768, 1024, false, null],
  ['06-bell-open-phone-dark', '/dashboard', 360, 740, true, async (p) => { await p.getByRole('button', { name: /Alerts:/ }).click() }],
  ['07-phone-menu-open-dark', `/clients/${CLIENT}/bookkeeping`, 360, 740, true, async (p) => { await p.getByRole('button', { name: 'Open menu' }).click() }],
  ['08-view-alerts-open-phone-dark', `/clients/${CLIENT}/bookkeeping`, 360, 740, true, async (p) => { await p.getByRole('button', { name: /View alerts/ }).click() }],
  ['09-alerts-page-desktop-light', '/alerts', 1440, 900, false, null],
]

const browser = await chromium.launch()
const problems = []
for (const [name, path, width, height, dark, action] of shots) {
  const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: dark ? 'dark' : 'light' })
  await ctx.addInitScript((d) => { try { localStorage.setItem('autoca.theme', d ? 'dark' : 'light') } catch {} }, dark)
  const page = await ctx.newPage()
  page.on('pageerror', (e) => problems.push(`${name}: ${e.message}`))
  page.on('console', (m) => { if (m.type() === 'error') problems.push(`${name}: console ${m.text().slice(0, 160)}`) })
  await page.goto(WEB + path, { waitUntil: 'networkidle' })
  await page.waitForTimeout(600)
  try { if (action) { await action(page); await page.waitForTimeout(500) } } catch (e) { problems.push(`${name}: action failed: ${String(e.message).split('\n')[0]}`) }
  // horizontal overflow check
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  if (overflow > 0) problems.push(`${name}: page is ${overflow}px wider than the window`)
  await page.screenshot({ path: `${OUT}/${name}.png` })
  await ctx.close()
}
await browser.close()
console.log(problems.length ? problems.join('\n') : 'no problems found')
