// Readings of the weekly work-flow figures. The two series are not like for like (a bank transfer is two
// statement rows but one entry, and finished also counts vouchers), so nothing here compares them or says
// work is piling up: it says what the numbers are.

import type { WorkFlow } from '@/api/types'
import { formatDate, plural } from '@/lib/format'
import { monthShort } from '@/lib/chartFormat'

/** "6 Oct" from an ISO date. */
export const weekLabel = (iso: string): string => `${Number(iso.slice(8, 10))} ${monthShort(iso.slice(0, 7))}`

/** The weeks, each marked partial when it starts before the period or runs past its end. */
export function markPartial(flow: WorkFlow) {
  const from = flow.period.from
  const to = flow.period.to
  return flow.weekly.map((w) => {
    const end = new Date(`${w.week_start}T00:00:00Z`)
    end.setUTCDate(end.getUTCDate() + 6)
    return { ...w, partial: w.week_start < from || end.toISOString().slice(0, 10) > to }
  })
}

/** "Finished 412 entries and received 388 rows in these 12 weeks (01-07-2026 to 22-09-2026)." */
export function flowSentence(flow: WorkFlow): string {
  const weeks = flow.weekly.length
  const { finished, received } = flow.totals
  return `Finished ${plural(finished, 'entry', 'entries')} and received ${plural(received, 'row')} in ${weeks === 1 ? 'this week' : `these ${weeks} weeks`} (${formatDate(flow.period.from)} to ${formatDate(flow.period.to)}).`
}
