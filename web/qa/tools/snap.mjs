#!/usr/bin/env node
// Look at one screen as one role: screenshot, readable text, and anything that went wrong.
//
//   node qa/tools/snap.mjs --as senior --path clients --name clients-senior
//   node qa/tools/snap.mjs --as admin --path clients --dark --width 390 --name clients-phone
//   node qa/tools/snap.mjs --as admin --path clients --api api/v1/clients/   # also print the API's answer

import { apiJson, shot, signedIn, visibleText, WEB } from '../lib/session.mjs'

const args = process.argv.slice(2)
const opt = (name, fallback) => {
  const i = args.indexOf(`--${name}`)
  return i === -1 ? fallback : args[i + 1]
}
const flag = (name) => args.includes(`--${name}`)

// Git Bash on Windows rewrites an argument that starts with "/" into a filesystem path,
// so paths may be given without the leading slash ("clients", "api/v1/clients/").
const slash = (p) => (p.startsWith('/') ? p : `/${p}`)

const role = opt('as', 'admin')
const path = slash(opt('path', '/clients'))
const name = opt('name', `${role}${path.replace(/[^a-z0-9]+/gi, '-')}`)

const { page, problems, close } = await signedIn(role, {
  width: Number(opt('width', 1440)),
  height: Number(opt('height', 900)),
  dark: flag('dark'),
})

try {
  await page.goto(`${WEB}${path}`)
  await page.waitForLoadState('networkidle')
  console.log(`# ${role} at ${path}\n`)
  console.log(`screenshot: ${await shot(page, name)}\n`)
  console.log('## What is on screen\n')
  console.log(await visibleText(page))
  const api = opt('api') && slash(opt('api'))
  if (api) {
    console.log(`\n## API ${api}\n`)
    console.log(JSON.stringify(await apiJson(page, api), null, 2))
  }
  console.log('\n## Problems\n')
  console.log(problems.length ? problems.join('\n') : 'none')
} finally {
  await close()
}
