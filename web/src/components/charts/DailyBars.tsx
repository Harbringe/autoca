import { lazy, Suspense } from 'react'
import { formatDate, plural } from '@/lib/format'
import { ChartTable } from './ChartTable'
import type { DayPoint } from './DailyBarsPlot'

const DailyBarsPlot = lazy(() => import('./DailyBarsPlot'))

/** "You finished 15 entries in this period." The chart's conclusion in words. */
export function dailySummary(days: DayPoint[]): string {
  const total = days.reduce((n, d) => n + d.finished, 0)
  const active = days.filter((d) => d.finished > 0).length
  if (total === 0) return 'Nothing has been finished in this period yet.'
  return `${plural(total, 'entry', 'entries')} finished on ${plural(active, 'day')}.`
}

/** Entries finished each day of the period, as plain bars with a tooltip and a hidden table. */
export function DailyBars({ days, className = 'h-48' }: { days: DayPoint[]; className?: string }) {
  const summary = dailySummary(days)
  return (
    <div>
      <div role="img" aria-label={`Entries finished each day. ${summary}`} className={className}>
        <Suspense fallback={<div className="skeleton size-full" />}>
          <DailyBarsPlot days={days} />
        </Suspense>
      </div>
      <p className="mt-2 text-[13px] text-muted-foreground">{summary}</p>
      <ChartTable caption="Entries finished each day" columns={['Day', 'Entries finished']} rows={days.map((d) => [formatDate(d.date), d.finished])} />
    </div>
  )
}
