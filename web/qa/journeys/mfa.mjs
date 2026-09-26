// The second factor, end to end, against real servers with MFA switched ON.
//
// Everyone else in the QA firm signs in with MFA off (a local convenience). Every
// real user does not, so this is the journey that matters: first sign-in (scan,
// confirm), sign out, sign in again (enter a code). Run against a second pair of
// servers so the reviewer's own session is not disturbed:
//
//   MFA_DISABLED=0 FRONTEND_URL=http://127.0.0.1:5174 python manage.py runserver 127.0.0.1:8001 --noreload
//   VITE_DEV_API=http://127.0.0.1:8001 npx vite --port 5174 --host 127.0.0.1
//   QA_WEB=http://127.0.0.1:5174 node qa/journeys/mfa.mjs
//
// It computes the six-digit code itself (RFC 6238) from the key the page shows.

import { chromium } from '@playwright/test'
import { totp } from '../lib/totp.mjs'
import { PASSWORD, PEOPLE, WEB, shot } from '../lib/session.mjs'

const results = []
const check = (name, ok, detail = '') => {
  results.push({ name, ok })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  (${detail})` : ''}`)
}

const browser = await chromium.launch()
const page = await (await browser.newContext({ viewport: { width: 1200, height: 900 } })).newPage()
const setupPosts = []
page.on('request', (r) => r.method() === 'POST' && r.url().includes('/auth/mfa/setup/') && setupPosts.push(r.url()))

async function signIn() {
  await page.goto(`${WEB}/`)
  await page.getByLabel('Email').fill(PEOPLE.mfa ?? 'qa.mfa@autoca.test')
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

// First sign-in: must be sent to set up, and the QR must belong to the device that verifies.
await signIn()
await page.getByRole('heading', { name: 'Set up your second factor' }).waitFor({ timeout: 15000 })
check('first sign-in shows the setup screen', true)
await page.getByAltText(/QR code/).waitFor()
check('a QR code is drawn', true)
const keyText = await page.locator('.select-all').innerText()
const secret = keyText.replace(/\s/g, '')
check('the manual key is shown', /^[A-Z2-7]{16,}$/.test(secret), secret ? `${secret.length} chars` : 'missing')
check('the device was provisioned exactly once (a second POST would orphan the QR on screen)', setupPosts.length === 1, `${setupPosts.length} POSTs`)
await shot(page, 'mfa-setup')

await page.getByLabel('6-digit code').fill('000000')
await page.getByRole('button', { name: /Turn on and continue/ }).click()
await page.getByRole('alert').waitFor()
check('a wrong code is refused with a message and no code number', !/\b40\d\b/.test(await page.getByRole('alert').innerText()), await page.getByRole('alert').innerText())

// django-otp deliberately delays the next attempt after a wrong one.
await page.waitForTimeout(3000)
await page.getByLabel('6-digit code').fill(totp(secret))
await page.getByRole('button', { name: /Turn on and continue/ }).click()
await page.getByRole('navigation', { name: 'Main' }).waitFor({ timeout: 15000 })
check('the right code completes sign-in and lands in the app', true)
const codeUsed = totp(secret)

// Sign out, sign in again: now it is a code, not a QR.
await page.getByRole('button', { name: 'Account and preferences' }).click()
await page.getByRole('menuitem', { name: /Sign out/ }).click()
await page.getByLabel('Email').waitFor()
await signIn()
await page.getByRole('heading', { name: 'Enter your code' }).waitFor({ timeout: 15000 })
check('second sign-in asks for a code, with no QR', (await page.getByAltText(/QR code/).count()) === 0)
await shot(page, 'mfa-verify')

// A code cannot be used twice, so wait for the next 30-second window.
while (totp(secret) === codeUsed) await page.waitForTimeout(1000)
await page.getByLabel('6-digit code').fill(totp(secret))
await page.getByRole('button', { name: 'Verify' }).click()
await page.getByRole('navigation', { name: 'Main' }).waitFor({ timeout: 15000 })
check('a fresh code signs in', true)

await browser.close()
const failed = results.filter((r) => !r.ok)
console.log(failed.length ? `\n${failed.length} FAILED` : '\nall passed')
process.exit(failed.length ? 1 : 0)
