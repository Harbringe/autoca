// The periods a work report is asked for in. Dates are ISO strings; nothing here touches a timezone
// beyond the local calendar day the person is looking at.

export type PeriodKey = 'month' | 'last' | 'fy' | 'custom'

export const PERIOD_LABEL: Record<PeriodKey, string> = {
  month: 'This month',
  last: 'Last month',
  fy: 'This financial year',
  custom: 'Custom dates',
}

export interface Range {
  from: string
  to: string
}

const p2 = (n: number) => String(n).padStart(2, '0')
export const isoOf = (d: Date) => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`

/** A preset's dates. "This" periods run to today: the future has no work in it. */
export function presetRange(key: Exclude<PeriodKey, 'custom'>, today: Date): Range {
  const y = today.getFullYear()
  const m = today.getMonth()
  switch (key) {
    case 'month':
      return { from: isoOf(new Date(y, m, 1)), to: isoOf(today) }
    case 'last':
      return { from: isoOf(new Date(y, m - 1, 1)), to: isoOf(new Date(y, m, 0)) }
    case 'fy':
      return { from: isoOf(new Date(m >= 3 ? y : y - 1, 3, 1)), to: isoOf(today) }
  }
}

const DAY = 86_400_000
const ms = (iso: string) => Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10)))

/** The server's rule, said before the request: the end is not before the start, and a year at most. */
export function rangeProblem(range: Range | null): string | null {
  if (!range) return 'Enter both dates as DD-MM-YYYY.'
  if (range.to < range.from) return 'The end date is before the start date.'
  if ((ms(range.to) - ms(range.from)) / DAY > 366) return 'Pick a period of a year or less.'
  return null
}
