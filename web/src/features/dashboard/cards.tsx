// The cards the three dashboards share, each one question long. They read the firm portfolio the server
// already scopes by role (a Senior CA sees their team's clients, Staff the clients they are on), so the
// same card is right for every layout. Figures are counts of clients and work, never a score for a person.

import { useMemo } from 'react'
import type { Portfolio, PortfolioClient } from '@/api/types'
import { ActionList } from '@/components/ca/ActionList'
import { DashCard, type CardState } from '@/components/ca/DashCard'
import { RankedBars } from '@/components/charts/RankedBars'
import { DueTimeline } from '@/components/charts/DueTimeline'
import { StackedBar, StackedBarSkeleton } from '@/components/charts/StackedBar'
import { ageSegmentsFromList, sumSegments } from '@/lib/ageing'
import { actionsFor, clientHealth, dueWithin, standingContext } from '@/lib/dashboard'
import { formatCompact, formatPaise } from '@/lib/format'

export interface CardProps {
  data: Portfolio | undefined
  state: CardState
}

/** "What falls due in the next 30 days?": the server's dated list as a line of dates, with the list beneath as the detail. */
export function DueSoonCard({ data, state, today }: CardProps & { today: Date }) {
  const rows = useMemo(() => dueWithin(data?.deadlines ?? [], 30, today), [data, today])
  return (
    <DashCard
      title="What falls due in the next 30 days?"
      state={state}
      skeleton="h-32"
    >
      <DueTimeline items={rows} today={today} />
    </DashCard>
  )
}

/** One side of the owed card: the total as a figure, then how old it is as a bar on the shared scale. */
function OwedSide({ title, empty, total, buckets, scaleMax }: { title: string; empty: string; total: number; buckets: { bucket: string; amount_paise: number }[] | undefined; scaleMax: number }) {
  const segments = ageSegmentsFromList(buckets ?? [])
  const bills = sumSegments(segments)
  const apart = total - bills
  return (
    <div className="grid gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-medium text-heading">{title}</h3>
        <span className="num text-2xl font-semibold text-heading" title={formatPaise(total)}>
          {formatCompact(total)}
        </span>
      </div>
      {buckets && (
        <>
          <StackedBar
            segments={segments}
            scaleMax={scaleMax}
            ariaLabel={`${title}: ${formatCompact(total)} in all, ${formatCompact(segments[3]!.value)} over 90 days old`}
            caption={`${title}, by age of the bill`}
            empty={empty}
          />
          {apart !== 0 && bills > 0 && (
            <p className="text-xs text-muted-foreground">
              Bar is bills only; {formatCompact(Math.abs(apart))} {apart < 0 ? 'held on account or as advances is taken off the total' : 'is not aged'}.
            </p>
          )}
        </>
      )}
    </div>
  )
}

/** "Who owes what, and how old?": the server's firm-wide roll-up, only where it sent money. Both sides share one scale. */
export function OwedCard({ data, state }: CardProps) {
  const receivable = data?.receivables_total_paise
  const payable = data?.payables_total_paise
  const top = data?.top_receivables ?? []
  const aging = data?.aging
  const present = receivable !== undefined && payable !== undefined
  const missing = state === 'ready' && !present
  const none = state === 'ready' && present && receivable === 0 && payable === 0
  const sum = (list: { amount_paise: number }[] | undefined) => (list ?? []).reduce((n, b) => n + Math.max(b.amount_paise, 0), 0)
  const scaleMax = Math.max(sum(aging?.receivables), sum(aging?.payables), 1)
  return (
    <DashCard
      title="Who owes what, and how old?"
      state={missing || none ? 'empty' : state}
      empty={missing ? 'Not shown for your role, or for firms with very many clients. Open a client to see its figures.' : 'No unpaid invoices or bills have been posted yet.'}
      skeleton="h-40"
      skeletonShape={<StackedBarSkeleton rows={2} />}
    >
      <div className="grid gap-5">
        <OwedSide title="Customers owe your clients" empty="No customer owes your clients anything." total={receivable ?? 0} buckets={aging?.receivables} scaleMax={scaleMax} />
        <OwedSide title="Your clients owe suppliers" empty="Your clients owe no supplier anything." total={payable ?? 0} buckets={aging?.payables} scaleMax={scaleMax} />
      </div>
      {top.length > 0 && (
        <div className="mt-4 border-t pt-3">
          <p className="mb-1 text-xs text-muted-foreground">Clients with the most to collect</p>
          <RankedBars
            rows={top.map((c) => ({
              key: c.client,
              label: c.client_name,
              value: c.amount_paise,
              valueLabel: formatCompact(c.amount_paise),
              to: '/clients/$clientId/reports',
              params: { clientId: c.client },
              search: { report: 'receivables' },
            }))}
          />
        </div>
      )}
    </DashCard>
  )
}

/** "Which clients are at risk, and why?": clients with a late or failing thing, with the reasons in words. */
export function AtRiskCard({ data, state, today, title = 'Which clients are at risk, and why?' }: CardProps & { today?: Date; title?: string }) {
  const rows = useMemo(
    () =>
      (data?.clients ?? [])
        .map((c) => ({ c, h: clientHealth(c, standingContext(data, today)) }))
        .filter((r) => r.h.health !== 'on_track')
        .sort((a, b) => Number(b.h.health === 'overdue') - Number(a.h.health === 'overdue') || b.h.reasons.length - a.h.reasons.length || a.c.name.localeCompare(b.c.name))
        .slice(0, 8),
    [data],
  )
  return (
    <DashCard title={title} hint="Late: a seal or TDS date has passed. At risk: a date within 7 days, or a month missing." state={state === 'ready' && rows.length === 0 ? 'empty' : state} empty="No client is at risk." to="/alerts" seeAll="See alerts" skeleton="h-48">
      <RankedBars
        rows={rows.map(({ c, h }) => ({
          key: c.id,
          label: c.name,
          value: h.reasons.length,
          valueLabel: h.health === 'overdue' ? 'Late' : 'At risk',
          note: h.reasons.join(' · '),
          to: '/clients/$clientId',
          params: { clientId: c.id },
          tone: h.health === 'overdue' ? 'danger' : 'accent',
        }))}
        max={Math.max(3, ...rows.map((r) => r.h.reasons.length))}
      />
    </DashCard>
  )
}

/** "What is waiting on me?" / "What should I do next?": the actions, each with its button. */
export function ActionCard({ data, state, today, title, hint, empty, limit = 8, pick }: CardProps & { today?: Date; title: string; hint: string; empty: string; limit?: number; pick?: (c: PortfolioClient) => boolean }) {
  const all = useMemo(() => actionsFor((data?.clients ?? []).filter(pick ?? (() => true)), standingContext(data, today)), [data, pick, today])
  return (
    <DashCard title={title} hint={hint} state={state === 'ready' && all.length === 0 ? 'empty' : state} empty={empty} skeleton="h-56">
      <ActionList items={all.slice(0, limit)} more={all.length - limit} moreTo="/pipeline" />
    </DashCard>
  )
}
