import { lazy, Suspense } from 'react'
import { formatPaise, plural } from '@/lib/format'
import { monthLong } from '@/lib/chartFormat'
import { ChartTable } from './ChartTable'
import type { MonthPoint } from './MonthBarsChart'

const MonthBarsChart = lazy(() => import('./MonthBarsChart'))

/** "Income was higher than expense in 8 of the 12 months with entries." The chart's conclusion in words. */
export function monthsSummary(trend: MonthPoint[]): string {
  const active = trend.filter((m) => m.income_paise > 0 || m.expense_paise > 0)
  if (active.length === 0) return 'Nothing has been posted in this financial year yet.'
  const higher = active.filter((m) => m.income_paise > m.expense_paise).length
  return `Income was higher than expense in ${higher} of the ${plural(active.length, 'month')} with entries.`
}

/** Income against expense for each month of the year, as paired bars with a legend, tooltips and a hidden table. */
export function MonthBars({ trend, className = 'h-64' }: { trend: MonthPoint[]; className?: string }) {
  const summary = monthsSummary(trend)
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-hidden>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm" style={{ background: 'var(--chart-1)' }} /> Money in
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm" style={{ background: 'var(--chart-2)' }} /> Money out
        </span>
      </div>
      <div role="img" aria-label={`Money in and out by month. ${summary}`} className={className}>
        <Suspense fallback={<div className="skeleton size-full" />}>
          <MonthBarsChart trend={trend} />
        </Suspense>
      </div>
      <p className="mt-2 text-[13px] text-muted-foreground">{summary}</p>
      <ChartTable
        caption="Money in and out by month"
        columns={['Month', 'Money in', 'Money out']}
        rows={trend.map((m) => [monthLong(m.month), formatPaise(m.income_paise), formatPaise(m.expense_paise)])}
      />
    </div>
  )
}
