// Labels for chart axes. Figures are paise integers; these only shorten them for a tick, in lakh and
// crore, and never round a figure up. The full amount is always in the tooltip and the hidden table.

import { formatCompact, groupIndian } from '@/lib/format'

const MONTH_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const MONTH_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

/** "₹0", "₹50,000", "₹1.5 L", "₹2 Cr": short enough for a y-axis tick. */
export function axisMoney(paise: number): string {
  const rupees = Math.trunc(Math.abs(Math.round(paise)) / 100)
  if (rupees < 100_000) return `${paise < 0 ? '-' : ''}₹${groupIndian(String(rupees))}`
  return formatCompact(paise)
}

/** "Apr" from "2026-04". */
export const monthShort = (ym: string): string => MONTH_SHORT[Number(ym.slice(5, 7)) - 1] ?? ym

/** "April 2026" from "2026-04". */
export const monthLong = (ym: string): string => `${MONTH_LONG[Number(ym.slice(5, 7)) - 1] ?? ym} ${ym.slice(0, 4)}`
