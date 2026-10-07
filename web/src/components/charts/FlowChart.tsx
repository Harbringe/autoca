import { lazy, Suspense } from 'react'
import type { WorkFlow } from '@/api/types'
import { flowSentence, markPartial, weekLabel } from '@/lib/flow'
import { ChartTable } from './ChartTable'

const FlowChartPlot = lazy(() => import('./FlowChartPlot'))

/**
 * Rows received and entries finished, week by week. The two are different things (a transfer is two rows but one
 * entry, and a voucher is finished without a row), so the card says what each is and never calls the gap a backlog.
 */
export function FlowChart({ flow, className = 'h-56' }: { flow: WorkFlow; className?: string }) {
  const weeks = markPartial(flow)
  const sentence = flowSentence(flow)
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-hidden>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm" style={{ background: 'var(--chart-muted)' }} /> Rows received
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-0.5 w-3 rounded" style={{ background: 'var(--chart-1)' }} /> Entries finished
        </span>
      </div>
      <div role="img" aria-label={`Rows received and entries finished each week. ${sentence}`} className={className}>
        <Suspense fallback={<div className="skeleton size-full" />}>
          <FlowChartPlot weeks={weeks} />
        </Suspense>
      </div>
      <p className="mt-2 text-[13px] text-heading">{sentence}</p>
      <p className="text-xs text-muted-foreground">Received counts statement rows; finished counts entries posted. They are not the same unit, so compare the trend, not the totals.</p>
      <ChartTable
        caption="Rows received and entries finished by week"
        columns={['Week starting', 'Rows received', 'Entries finished']}
        rows={weeks.map((w) => [`${weekLabel(w.week_start)}${w.partial ? ' (part of a week)' : ''}`, w.received, w.finished])}
      />
    </div>
  )
}
