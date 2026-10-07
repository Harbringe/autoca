// Screenshots of the dashboards against qa/tools/mock-api-dash.mjs (port 8001) through the dev server on 5174.
//   node qa/tools/dash-shots.mjs <output folder> [role,role] [widths] [dark|light|both] [pathFilter]
import { createRequire } from 'node:module'
import fs from 'node:fs'
const require = createRequire(import.meta.url)
const { chromium } = require('playwright')

const OUT = process.argv[2]
const roles = (process.argv[3] || 'FIRM_ADMIN,SENIOR_CA,STAFF').split(',')
const widths = (process.argv[4] || '1440,1024,768,360').split(',').map(Number)
const themes = process.argv[5] === 'dark' ? [true] : process.argv[5] === 'light' ? [false] : [false, true]
const only = process.argv[6]
fs.mkdirSync(OUT, { recursive: true })
const WEB = 'http://127.0.0.1:5174'
const paths = [['dash', '/dashboard'], ['client', '/clients/c0000000-0000-4000-8000-000000000001/bookkeeping'], ['client3', '/clients/c0000000-0000-4000-8000-000000000003/bookkeeping'], ['client5', '/clients/c0000000-0000-4000-8000-000000000005/bookkeeping']].filter(([n]) => !only || only.split(',').includes(n))

const browser = await chromium.launch()
const problems = []
for (const role of roles) {
  for (const [pname, path] of paths) {
    if (pname !== 'dash' && role === 'STAFF' && pname !== 'client') continue
    for (const width of widths) {
      for (const dark of themes) {
        // the dark theme is only looked at on the widest and the narrowest screen
        if (dark && width !== 1440 && width !== 360) continue
        const name = `${role}-${pname}-${width}${dark ? '-dark' : ''}`
        const ctx = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: dark ? 'dark' : 'light' })
        await ctx.addCookies([{ name: 'mockrole', value: role, url: WEB }])
        await ctx.addInitScript((d) => { try { localStorage.setItem('autoca.theme', d ? 'dark' : 'light') } catch {} }, dark)
        const page = await ctx.newPage()
        page.on('pageerror', (e) => problems.push(`${name}: ${e.message}`))
        page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') problems.push(`${name}: console ${m.type()} ${m.text().slice(0, 200)}`) })
        await page.goto(WEB + path, { waitUntil: 'networkidle' })
        await page.waitForTimeout(900)
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
        if (overflow > 0) problems.push(`${name}: page is ${overflow}px wider than the window`)
        await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true })
        await ctx.close()
      }
    }
  }
}
await browser.close()
console.log(problems.length ? problems.join('\n') : 'no problems found')
