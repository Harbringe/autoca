#!/usr/bin/env node
// A bank statement PDF with nothing real in it, for building and testing the app.
//
// Every name, number and amount is invented. The layout is an ordinary Indian net-banking
// export -- header with account number, IFSC and period; a bordered table of Date,
// Narration, Ref, Value date, Withdrawal, Deposit, Balance -- and the running balance chains
// exactly, so the parser reads it as it would a real one.
//
//   node qa/tools/make-statement.mjs                       # April 2025 -> qa/samples/qa-sharma-traders-2025-04.pdf
//   node qa/tools/make-statement.mjs --month 2025-05 --opening 187432.15
//   node qa/tools/make-statement.mjs --holder "QA GUPTA EXPORTS" --account 91820000777777
//
// Months chain: pass the previous month's closing balance as --opening for the next one.

import { chromium } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const args = process.argv.slice(2)
const opt = (name, fallback) => {
  const i = args.indexOf(`--${name}`)
  return i === -1 ? fallback : args[i + 1]
}
const month = opt('month', '2025-04')
const openingRupees = Number(opt('opening', '125000.00'))
const holder = opt('holder', 'QA SHARMA TRADERS')
const accountNo = opt('account', '91820000123456')
const slug = holder.toLowerCase().replace(/[^a-z0-9]+/g, '-')
const [year, mon] = month.split('-').map(Number)
const daysIn = new Date(year, mon, 0).getDate()

// Invented counterparties, each with a recurring pattern, so rules have something to learn.
const pattern = [
  [2, `UPI/501234567890/${holder}/Payment to ZEPTO MARKETPLACE`, 'UPI', 1845.0, 0],
  [3, 'NEFT CR-HDFC0001234-ORBIT RETAIL PVT LTD-INV 1042', 'N0412345678', 0, 86500.0],
  [5, 'ACH D- MAHAVITARAN ELECTRICITY BILL', 'ACH', 4312.0, 0],
  [5, `UPI/501234567891/${holder}/Payment to ZEPTO MARKETPLACE`, 'UPI', 962.5, 0],
  [7, 'NEFT DR-SBIN0004321-SUNRISE PACKAGING CO-PO 77', 'N0712345678', 24750.0, 0],
  [8, 'ATW-4321-CASH WDL-PUNE CAMP', '', 10000.0, 0],
  [10, `IMPS/P2A/${holder}/RENT APR TO KAVERI ESTATES`, 'IMPS', 32000.0, 0],
  [12, 'NEFT CR-ICIC0000456-LOTUS DISTRIBUTORS LLP-INV 1043', 'N1212345678', 0, 54200.0],
  [14, `UPI/501234567892/${holder}/Payment to ZEPTO MARKETPLACE`, 'UPI', 2210.0, 0],
  [15, 'SALARY PAID - STAFF APR BATCH', 'BULK', 48000.0, 0],
  [16, 'NEFT DR-SBIN0004321-SUNRISE PACKAGING CO-PO 81', 'N1612345678', 18300.0, 0],
  [18, 'ACH D- JIO FIBER BROADBAND', 'ACH', 1178.82, 0],
  [19, 'NEFT CR-HDFC0001234-ORBIT RETAIL PVT LTD-INV 1047', 'N1912345678', 0, 92250.0],
  [21, 'GST PAYMENT CPIN 25040012345678', 'GST', 11420.0, 0],
  [22, `UPI/501234567893/${holder}/Payment to ZEPTO MARKETPLACE`, 'UPI', 1399.0, 0],
  [24, 'NEFT DR-UTIB0000789-BLUE DART EXPRESS-AWB', 'N2412345678', 3860.0, 0],
  [26, 'NEFT CR-ICIC0000456-LOTUS DISTRIBUTORS LLP-INV 1049', 'N2612345678', 0, 61800.0],
  [27, 'CHQ DEP-000412-CLEARING-MEHTA HARDWARE', '000412', 0, 15600.0],
  [28, 'SMS ALERT CHARGES QTR', '', 17.7, 0],
  [daysIn, `INT.PD:01-${String(mon).padStart(2, '0')}-${year} to ${daysIn}-${String(mon).padStart(2, '0')}-${year}`, '', 0, 684.0],
]

const pad = (n) => String(n).padStart(2, '0')
const dd = (day) => `${pad(day)}/${pad(mon)}/${String(year).slice(2)}`
const paise = (r) => Math.round(r * 100)
const money = (p) => {
  if (!p) return ''
  const s = (p / 100).toFixed(2)
  const [int, dec] = s.split('.')
  const head = int.slice(0, -3)
  const grouped = head ? head.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + int.slice(-3) : int
  return `${grouped}.${dec}`
}

let balance = paise(openingRupees)
const opening = balance
let debits = 0
let credits = 0
const rows = pattern.map(([day, narration, ref, wd, dep]) => {
  const w = paise(wd)
  const d = paise(dep)
  balance = balance - w + d
  debits += w
  credits += d
  return `<tr><td>${dd(day)}</td><td>${narration}</td><td>${ref}</td><td>${dd(day)}</td><td class=n>${money(w)}</td><td class=n>${money(d)}</td><td class=n>${money(balance)}</td></tr>`
})

const html = `<!doctype html><html><head><meta charset=utf-8><style>
  body { font: 10px Arial, sans-serif; margin: 24px; }
  h1 { font-size: 14px; margin: 0 0 6px; }
  table { border-collapse: collapse; width: 100%; margin-top: 10px; }
  td, th { border: 1px solid #333; padding: 3px 4px; vertical-align: top; }
  th { background: #eee; }
  .n { text-align: right; white-space: nowrap; }
</style></head><body>
<h1>QA DEMO BANK LTD</h1>
<div>Statement of account</div>
<div>Account Name : ${holder}</div>
<div>Account No : ${accountNo}</div>
<div>IFSC : QADB0000123</div>
<div>From : 01/${pad(mon)}/${year} To : ${pad(daysIn)}/${pad(mon)}/${year}</div>
<table>
<tr><th>Date</th><th>Narration</th><th>Chq/Ref No</th><th>Value Dt</th><th>Withdrawal Amt.</th><th>Deposit Amt.</th><th>Closing Balance</th></tr>
<tr><td>01/${pad(mon)}/${String(year).slice(2)}</td><td>OPENING BALANCE</td><td></td><td></td><td class=n></td><td class=n></td><td class=n>${money(opening)}</td></tr>
${rows.join('\n')}
<tr><td>${dd(daysIn)}</td><td>CLOSING BALANCE</td><td></td><td></td><td class=n></td><td class=n></td><td class=n>${money(balance)}</td></tr>
</table>
<p>Synthetic statement for software testing. Not a real account.</p>
</body></html>`

const here = dirname(fileURLToPath(import.meta.url))
const out = resolve(here, '..', 'samples', `${slug}-${month}.pdf`)
mkdirSync(dirname(out), { recursive: true })
const browser = await chromium.launch()
const page = await browser.newPage()
await page.setContent(html)
await page.pdf({ path: out, format: 'A4', printBackground: true })
await browser.close()

console.log(JSON.stringify({ file: out, month, rows: pattern.length, opening: money(opening), debits: money(debits), credits: money(credits), closing: money(balance), closing_rupees: (balance / 100).toFixed(2) }, null, 2))
