// Drive the running web app the way a person in the firm would.
//
// The reviewer never touches the code or the database: it signs in as one of the
// synthetic QA people (scripts/qa_seed.py), looks at screens, and compares what
// it sees with what the API says. Everything here is read-and-click; nothing is
// mocked, so what it reports is what a real user would have met.

import { chromium } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export const WEB = process.env.QA_WEB ?? 'http://127.0.0.1:5173'
export const PASSWORD = process.env.QA_PASSWORD ?? 'qa-synthetic-Passw0rd-2026'
export const PEOPLE = {
  admin: 'qa.admin@autoca.test',
  senior: 'qa.senior@autoca.test',
  staff: 'qa.staff@autoca.test',
  reader: 'qa.reader@autoca.test',
}

const here = dirname(fileURLToPath(import.meta.url))
export const SHOTS = resolve(here, '..', 'screenshots')

/**
 * Open a browser signed in as `role`. Returns { page, context, browser, problems, close }.
 * `problems` fills up, as the page runs, with console errors, page errors and API calls
 * that failed -- the things a person would feel as "it glitched" without being able to say why.
 */
export async function signedIn(role = 'admin', { width = 1440, height = 900, dark = false } = {}) {
  const browser = await chromium.launch()
  const context = await browser.newContext({
    viewport: { width, height },
    colorScheme: dark ? 'dark' : 'light',
    locale: 'en-IN',
    timezoneId: 'Asia/Kolkata',
  })
  const page = await context.newPage()
  const problems = []
  // Signing in starts with a "who am I?" that is refused, by design. That is not a fault,
  // so nothing is recorded until the person is through.
  let watching = false
  page.on('console', (m) => watching && m.type() === 'error' && problems.push(`console: ${m.text()}`))
  page.on('pageerror', (e) => watching && problems.push(`page error: ${e.message}`))
  page.on('response', (r) => {
    const url = r.url()
    if (watching && r.status() >= 400 && /\/(api|auth)\//.test(url)) problems.push(`${r.status()} ${r.request().method()} ${url.replace(WEB, '')}`)
  })

  await page.goto(`${WEB}/`)
  await page.getByLabel('Email').fill(PEOPLE[role])
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  // MFA is switched off for local development, so the shell appears straight away.
  await page.getByRole('navigation', { name: 'Main' }).waitFor({ timeout: 15000 })
  watching = true

  return { page, context, browser, problems, close: () => browser.close() }
}

/** Fetch an API path as the signed-in person, for comparing what is shown with what is true. */
export async function apiJson(page, path) {
  const response = await page.request.get(`${WEB}${path}`)
  if (!response.ok()) throw new Error(`${response.status()} ${path}`)
  return response.json()
}

/** Screenshot to web/qa/screenshots/<name>.png (a full page, so nothing below the fold is missed). */
export async function shot(page, name) {
  const file = resolve(SHOTS, `${name}.png`)
  mkdirSync(dirname(file), { recursive: true })
  await page.screenshot({ path: file, fullPage: true })
  return file
}

/** The text a person can actually read on the page, in order. */
export async function visibleText(page) {
  return page.locator('body').innerText()
}
