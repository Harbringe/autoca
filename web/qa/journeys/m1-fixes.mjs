// Regression checks for the M1 re-verification findings (M1-008, M1-011, M1-012).
import { signedIn, WEB } from '../lib/session.mjs'

const results = []
const check = (name, ok, detail = '') => {
  results.push(ok)
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  (${detail})` : ''}`)
}
const { page, close } = await signedIn('admin')
try {
  // M1-011: Enter straight after typing must never open a client the text does not match.
  for (const text of ['dark', 'zzzq']) {
    await page.goto(`${WEB}/clients`)
    await page.getByRole('button', { name: 'Add' }).first().waitFor().catch(() => {})
    await page.keyboard.press('Control+k')
    await page.getByPlaceholder(/Search clients/).waitFor()
    await page.keyboard.type(text)
    await page.keyboard.press('Enter') // immediately, inside the debounce window
    await page.waitForTimeout(1200)
    check(`Ctrl+K "${text}" then Enter at once does not open a client`, !/\/clients\/[0-9a-f-]{36}/.test(page.url()), page.url().replace(WEB, ''))
  }

  // M1-008: the very first open of the dialog must protect typed text.
  await page.goto(`${WEB}/clients`)
  await page.getByRole('button', { name: 'New client' }).click()
  await page.getByLabel('Client name').fill('QA Discard Test')
  await page.keyboard.press('Escape')
  check('Esc on the first-ever open asks before discarding', await page.getByText('Discard what you have typed?').first().isVisible())

  // M1-012: focus stays in the prompt, and Esc means keep editing.
  await page.keyboard.press('Tab')
  const inside = await page.evaluate(() => !!document.activeElement?.closest('[role="alertdialog"]') || document.activeElement?.tagName === 'BUTTON')
  check('Tab does not reach the fields behind the prompt', inside && (await page.getByLabel('Client name').isDisabled()))
  await page.keyboard.press('Escape')
  check('Esc on the prompt keeps the text and returns to editing', (await page.getByLabel('Client name').inputValue()) === 'QA Discard Test')
} finally {
  await close()
}
process.exit(results.every(Boolean) ? 0 : 1)
