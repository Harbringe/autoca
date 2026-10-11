// The picture above a report's table. Every report keeps its table (it is the document that is printed and audited); the
// picture answers the question first. Pictures are not printed, so the printed report is unchanged.

import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { isApiError } from '@/api/errors'
import { clientSnapshot } from '@/api/queries/dashboard'
import { ErrorState } from '@/components/ca/Page'
import { ColumnSkeleton, EmptyPlot } from '@/components/charts/ColumnChart'
import { MonthBars } from '@/components/charts/MonthBars'
import { StackedBarSkeleton } from '@/components/charts/StackedBar'
import { Card } from '@/components/ui/card'
import { hasPosted } from '@/features/clients/FinancialSnapshot'
import { useSession } from '@/session/session'

/** A titled picture, hidden when printing. */
export function Picture({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section aria-label={title} className={`no-print mb-5 rounded-lg border bg-surface-2 p-4 ${className ?? ''}`}>
      <h3 className="mb-3 text-sm font-semibold text-heading">{title}</h3>
      {children}
    </section>
  )
}

/** What a report shows while it prepares: the shape of its picture and of its table, not a spinner. */
export function ReportSkeleton({ label = 'Preparing the report…' }: { label?: string }) {
  return (
    <Card className="p-5" aria-busy="true">
      <span className="sr-only">{label}</span>
      <div aria-hidden className="grid gap-5">
        <div className="skeleton mx-auto h-4 w-48 rounded" />
        <StackedBarSkeleton />
        <div className="grid gap-2">
          {Array.from({ length: 6 }, (_, i) => (
            <span key={i} className="skeleton h-5 rounded" />
          ))}
        </div>
      </div>
    </Card>
  )
}

/** The month-by-month money in and out of the financial year, from the client snapshot (the same figures as the client page). */
export function MonthlyTrend({ clientId, fy }: { clientId: string; fy: number }) {
  const { can } = useSession()
  const q = useQuery({ ...clientSnapshot(clientId, fy), enabled: can('journal.view') })
  if (!can('journal.view')) return null
  if (isApiError(q.error) && q.error.status === 403) return null
  return (
    <Picture title="Money in and out, month by month">
      {q.isLoading ? (
        <ColumnSkeleton />
      ) : q.error ? (
        <ErrorState error={q.error} retry={() => void q.refetch()} />
      ) : q.data && hasPosted(q.data) ? (
        <MonthBars trend={q.data.trend} className="h-56" />
      ) : (
        <EmptyPlot line="Nothing has been posted in this year yet. Entries you post appear here by month." />
      )}
    </Picture>
  )
}
