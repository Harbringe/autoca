// How this product writes down money and dates.
//
// Indian books group digits as 12,34,567.00 (lakh and crore), write dates
// DD-MM-YYYY, and run the financial year April to March. None of that is what
// the platform's defaults do, so it is done here, once, and every screen calls
// it. The server already sends a formatted `*_display` beside every amount; use
// that when there is one. This is for the figures that arrive as bare paise
// (GST) and for anything computed in the browser.

const RUPEE = '₹'

/** 1234567 -> "12,34,567". Integer-exact; no floating point is involved. */
export function groupIndian(digits: string): string {
  if (digits.length <= 3) return digits
  const head = digits.slice(0, -3)
  const tail = digits.slice(-3)
  return head.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + tail
}

export interface MoneyOptions {
  /** Prefix the rupee sign. Default true. */
  symbol?: boolean
  /** Show a leading "-" for negatives. Default true; ledgers use Dr/Cr instead. */
  sign?: boolean
}

/** 123456789 paise -> "₹12,34,567.89". */
export function formatPaise(paise: number, { symbol = true, sign = true }: MoneyOptions = {}): string {
  const negative = paise < 0
  const abs = Math.abs(Math.round(paise))
  const rupees = Math.trunc(abs / 100)
  const paisa = String(abs % 100).padStart(2, '0')
  const body = `${groupIndian(String(rupees))}.${paisa}`
  return `${negative && sign ? '-' : ''}${symbol ? RUPEE : ''}${body}`
}

/**
 * A balance the way a ledger writes it: an amount and a side, never a signed
 * number. `net` is debit minus credit; zero has no side.
 */
export function formatDrCr(net: number, options: Omit<MoneyOptions, 'sign'> = {}): string {
  if (net === 0) return formatPaise(0, { ...options, sign: false })
  return `${formatPaise(Math.abs(net), { ...options, sign: false })} ${net > 0 ? 'Dr' : 'Cr'}`
}

/**
 * Rupees typed by a person -> paise. Accepts "1,23,456.5", "₹ 500", "500.00".
 * Returns null for anything that is not an amount, including more than two
 * decimal places: silently rounding a figure someone typed is how books drift.
 */
export function parseRupees(input: string): number | null {
  const cleaned = input.replace(/[\s,₹]/g, '').replace(/^Rs\.?/i, '')
  const match = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(cleaned)
  if (!match) return null
  const [, negative, rupees, paisa = ''] = match
  const paise = Number(rupees) * 100 + Number(paisa.padEnd(2, '0'))
  if (!Number.isSafeInteger(paise)) return null
  return negative ? -paise : paise
}

/**
 * A date typed the way it is written here -- 15-04-2025, 15/4/2025, 15.04.2025 -- to ISO
 * (2025-04-15). Null for anything that is not a real calendar date.
 */
export function parseDate(input: string): string | null {
  const match = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$/.exec(input.trim())
  if (!match) return null
  const [day, month, year] = [Number(match[1]), Number(match[2]), Number(match[3])]
  const d = new Date(Date.UTC(year, month - 1, day))
  if (d.getUTCFullYear() !== year || d.getUTCMonth() !== month - 1 || d.getUTCDate() !== day) return null
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2025-04-01" -> "01-04-2025". Pure string work, so no timezone can move the day. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  return match ? `${match[3]}-${match[2]}-${match[1]}` : iso
}

/** "2025-04-01" -> "1 Apr 2025", for prose and headings. */
export function formatDateLong(iso: string | null | undefined): string {
  if (!iso) return '—'
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!match) return iso
  return `${Number(match[3])} ${MONTHS[Number(match[2]) - 1]} ${match[1]}`
}

/** A timestamp in the viewer's own clock: "25-09-2026, 14:05". */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getDate())}-${p(d.getMonth() + 1)}-${d.getFullYear()}, ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 2025 -> "2025-26". The number is the year the financial year starts in. */
export function fyLabel(startYear: number): string {
  return `${startYear}-${String((startYear + 1) % 100).padStart(2, '0')}`
}

/** The financial year (by starting year) that a date falls in. April to March. */
export function financialYearOf(date: Date | string): number {
  const d = typeof date === 'string' ? new Date(`${date.slice(0, 10)}T00:00:00`) : date
  return d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1
}

/** First and last day of a financial year, as ISO dates. */
export function fyRange(startYear: number): { from: string; to: string } {
  return { from: `${startYear}-04-01`, to: `${startYear + 1}-03-31` }
}

/** "as at 31-03-2026" -- the wording a balance sheet's date is given in. */
export function asAt(startYear: number): string {
  return `as at ${formatDate(fyRange(startYear).to)}`
}

/** "2025-09" -> "Sep 2025", for a GST return period. */
export function formatPeriod(period: string): string {
  const match = /^(\d{4})-(\d{2})/.exec(period)
  return match ? `${MONTHS[Number(match[2]) - 1]} ${match[1]}` : period
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`
}
