// An invitation, end to end: the admin invites someone, the link opens the accept screen,
// the invitee sets a password, then meets the second factor for the first time.
//
// Needs the second server pair (see mfa.mjs). The admin's invite is made against the
// MFA-off server on :8000 (QA_API), the invitee then works on the MFA-on app at QA_WEB.

import { chromium, request } from '@playwright/test'
import { totp } from '../lib/totp.mjs'
import { PASSWORD, PEOPLE, WEB } from '../lib/session.mjs'

const API = process.env.QA_API ?? 'http://127.0.0.1:8000'
const results = []
const check = (name, ok, detail = '') => {
  results.push({ name, ok })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  (${detail})` : ''}`)
}

// --- the admin invites someone (over the API, as the app would) -------------
const admin = await request.newContext({ baseURL: API })
const csrf = async () => (await (await admin.get('/auth/csrf/')).json()).csrfToken
let token = await csrf()
const login = await admin.post('/auth/login/', { data: { email: PEOPLE.admin, password: PASSWORD }, headers: { 'X-CSRFToken': token } })
token = await csrf()
const email = `qa.invited.${Date.now()}@autoca.test`
const invited = await admin.post('/api/v1/team/members/', {
  data: { email, full_name: 'Ishaan Invited', role: 'STAFF' },
  headers: { 'X-CSRFToken': token },
})
check('the admin can invite (201)', login.ok() && invited.status() === 201, `login ${login.status()}, invite ${invited.status()}`)
const link = (await invited.json()).link
const inviteToken = link.split('/invite/')[1]
check('the link points at the web application', /^https?:\/\/[^/]+\/invite\/.+/.test(link), link)

// --- the invitee opens it ----------------------------------------------------
const browser = await chromium.launch()
const page = await (await browser.newContext({ viewport: { width: 1200, height: 900 } })).newPage()

await page.goto(`${WEB}/invite/${inviteToken}`)
await page.getByRole('heading', { name: /Join QA Associates/ }).waitFor({ timeout: 15000 })
check('the invitation names the firm', true)
const shown = await page.locator('body').innerText()
check('it says which role they are joining as', /Staff/.test(shown))
check('their email is shown and cannot be edited', await page.getByLabel('Email').isDisabled())

await page.getByLabel('Your name').fill('Ishaan Invited')
await page.getByLabel(/Choose a password/).fill('short')
const [weakResponse] = await Promise.all([
  page.waitForResponse((r) => r.url().includes('/auth/invite/') && r.request().method() === 'POST'),
  page.getByRole('button', { name: 'Accept invitation' }).click(),
])
await page.waitForTimeout(500)
const weak = await page.locator('body').innerText()
if (process.env.QA_DEBUG) console.log('--- after weak password ---', weak)
check('a weak password is refused (400)', weakResponse.status() === 400, `${weakResponse.status()}`)
check(
  'and the reason appears next to the field, replacing the hint',
  /This password/i.test(weak) && !/A phrase is easiest/.test(weak),
  weak.split('\n').find((line) => /This password/i.test(line)) ?? 'no reason shown',
)

await page.getByLabel(/Choose a password/).fill('Zebra-lantern-orbit-42')
await page.getByRole('button', { name: 'Accept invitation' }).click()
await page.getByRole('heading', { name: 'Set up your second factor' }).waitFor({ timeout: 20000 })
check('accepting signs them in and goes straight to second-factor setup', true)

await page.getByAltText(/QR code/).waitFor()
const secret = (await page.locator('.select-all').innerText()).replace(/\s/g, '')
await page.getByLabel('6-digit code').fill(totp(secret))
await page.getByRole('button', { name: /Turn on and continue/ }).click()
await page.getByRole('navigation', { name: 'Main' }).waitFor({ timeout: 15000 })
check('enrolling lands them in the app', true)
await page.getByText('No clients assigned to you').waitFor({ timeout: 10000 }).catch(() => {})
const body = await page.locator('body').innerText()
if (process.env.QA_DEBUG) console.log('--- after enrol ---', body)
check('a new staff member with no assignments sees no clients, and is told why', /No clients assigned to you/.test(body))

// --- the same link cannot be used twice --------------------------------------
const again = await (await browser.newContext()).newPage()
await again.goto(`${WEB}/invite/${inviteToken}`)
await again.getByRole('heading', { name: /can.t be used/ }).waitFor({ timeout: 15000 })
check('a used invitation is refused', true)

const forged = await (await browser.newContext()).newPage()
await forged.goto(`${WEB}/invite/00000000-0000-0000-0000-000000000000.forged`)
await forged.getByRole('heading', { name: /can.t be used/ }).waitFor({ timeout: 15000 })
check('a forged invitation is refused', true)

await browser.close()
await admin.dispose()
const failed = results.filter((r) => !r.ok)
console.log(failed.length ? `\n${failed.length} FAILED` : '\nall passed')
process.exit(failed.length ? 1 : 0)
