// Work & performance: what people did in a period, and what is waiting on them now.
//
// Counts only, in the order people are named: nobody is ranked, scored or compared. The owner sees
// everyone, an administrator sees the whole firm, a Senior CA sees their team, and
// everyone else sees their own work. What is "waiting now" is not history, so it does not change
// with the period.

import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useMemo } from 'react'
import { memberWork, teamMembers } from '@/api/queries/team'
import type { MemberWithWork, MemberWork, MetricKey } from '@/api/types'
import { EmptyState, ErrorState, PageHeader } from '@/components/ca/Page'
import { Spinner } from '@/components/ui/spinner'
import { StatCard, StatGrid } from '@/components/ui/stat-card'
import { DataTable, type Column } from '@/components/ui/table'
import { formatDate, plural } from '@/lib/format'
import { rangeFor, type PeriodKey, type Range } from '@/lib/period'
import { usePageTitle } from '@/lib/title'
import { MeasuredFigures } from './MeasuredFigures'
import { PeriodPicker } from './PeriodPicker'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'

export interface WorkSearch {
  period?: PeriodKey
  from?: string
  to?: string
  member?: string
}

const PERIODS: PeriodKey[] = ['month', 'last', 'fy', 'custom']
const ISO = /^\d{4}-\d{2}-\d{2}$/
const text = (v: unknown) => (typeof v === 'string' && v ? v : undefined)

/** The address's period, dates and person, kept only when they are well-formed. */
export function parseWorkSearch(search: Record<string, unknown>): WorkSearch {
  return {
    period: PERIODS.includes(search.period as PeriodKey) ? (search.period as PeriodKey) : undefined,
    from: typeof search.from === 'string' && ISO.test(search.from) ? search.from : undefined,
    to: typeof search.to === 'string' && ISO.test(search.to) ? search.to : undefined,
    member: text(search.member),
  }
}

export function WorkScreen({ search }: { search: WorkSearch }) {
  const { can, me } = useSession()
  const navigate = useNavigate({ from: '/staff' })
  const firmView = can('team.view')
  usePageTitle(firmView ? 'Staff performance' : 'My work')

  const key: PeriodKey = search.period ?? 'month'
  const range: Range | null = useMemo(() => rangeFor(key, search.from, search.to), [key, search.from, search.to])

  const memberId = (firmView ? search.member : undefined) ?? me?.membership_id ?? undefined
  const go = (next: { period?: PeriodKey; from?: string; to?: string; member?: string }) =>
    void navigate({ search: (prev) => ({ ...prev, ...next }), replace: true })

  return (
    <div className="grid gap-8 [&>*]:min-w-0">
      <div>
        <PageHeader
          title={firmView ? 'Staff performance' : 'My work'}
          description={
            firmView
              ? 'What each person did in the period, and what is waiting on them now. Counts only: no rankings.'
              : 'What you did in the period, and what is waiting on you now.'
          }
        />
        <PeriodPicker key={`${key}${range?.from}${range?.to}`} value={key} range={range} onPick={go} />
        <p className="mt-3 max-w-3xl text-[13px] text-muted-foreground">
          Not counted yet: books sent for review, and clients still to send for review. The server does not record them per person.
        </p>
      </div>

      {firmView && range && (
        <>
          <MeasuredFigures range={range} />
          <People range={range} selected={memberId} onSelect={(id) => go({ member: id })} title={can('member.manage') ? 'Firm activity' : 'Team activity'} />
        </>
      )}
      {memberId && range && <PersonWork memberId={memberId} range={range} heading={firmView} />}
      {!memberId && !firmView && <EmptyState title="Nothing to show">Your work appears here once you are on a firm.</EmptyState>}
    </div>
  )
}

const count = (n: number) => (n === 0 ? <span className="text-faint">0</span> : n)

function People({ range, selected, onSelect, title }: { range: Range; selected?: string; onSelect: (id: string) => void; title: string }) {
  const members = useQuery(teamMembers(range))
  if (members.isPending) return <Spinner label="Adding up the work…" />
  if (members.error) return <ErrorState error={members.error} retry={() => void members.refetch()} />
  const { metrics, results } = members.data
  // Alphabetical, on purpose: the order never says who did more. Columns are not sortable for the same reason.
  const people = [...results].sort((a, b) => a.name.localeCompare(b.name))
  const total = (k: MetricKey) => people.reduce((sum, p) => sum + p.work[k], 0)
  const active = people.filter((person) => person.is_active).length
  const columns: Column<MemberWithWork>[] = [
    {
      key: 'person',
      header: 'Person',
      cell: (p) => (
        <div>
          <button
            type="button"
            className="text-left font-medium text-heading hover:underline"
            aria-label={`Show ${p.name}’s work in detail`}
            aria-pressed={p.id === selected}
            onClick={() => onSelect(p.id)}
          >
            {p.name}
          </button>
          <div className="text-[13px] text-muted-foreground">
            {p.role_display}
            {p.manager && ` · reports to ${p.manager.name}`}
            {!p.is_active && ' · deactivated'}
          </div>
        </div>
      ),
    },
    ...metrics.map<Column<MemberWithWork>>((m, i) => ({
      key: m.key,
      header: m.label,
      align: 'right',
      priority: i < 2 ? 1 : 3,
      cell: (p) => count(p.work[m.key]),
    })),
  ]
  return (
    <section aria-labelledby="people-work" className="grid gap-3">
      <div>
        <h2 id="people-work" className="text-[15px] font-semibold text-heading">{title}</h2>
        <p className="text-[13px] text-muted-foreground">{plural(active, 'active person', 'active people')} · totals for the selected period</p>
      </div>
      <StatGrid className="xl:grid-cols-4">
        {metrics.map((metric) => (
          <StatCard key={metric.key} label={metric.label} value={total(metric.key)} />
        ))}
      </StatGrid>
      <DataTable
        caption="Work done by each person in the period"
        columns={columns}
        rows={people}
        rowKey={(p) => p.id}
        selectedKey={selected}
        footer={
          people.length > 1 ? (
            <tr>
              <th scope="row" className="px-3 py-2 text-left">All shown</th>
              {metrics.map((m, i) => (
                <td key={m.key} className={cn('num px-3 py-2 text-right', i >= 2 && 'max-lg:hidden')}>
                  {total(m.key)}
                </td>
              ))}
            </tr>
          ) : undefined
        }
      />
    </section>
  )
}

type ByClient = MemberWork['by_client'][number]
type OpenWork = MemberWork['open_work'][number]

function PersonWork({ memberId, range, heading }: { memberId: string; range: Range; heading: boolean }) {
  const work = useQuery(memberWork(memberId, range))
  if (work.isPending) return <Spinner label="Loading…" />
  if (work.error) return <ErrorState error={work.error} retry={() => void work.refetch()} />
  const w = work.data
  const shownMetrics = w.metrics.filter((m) => w.by_client.some((c) => c[m.key] > 0))
  const activeDays = w.by_day.filter((d) => d.count > 0).length
  const waiting = w.open_work.filter((c) => c.unresolved > 0 || c.pending_approval > 0)

  const byClient: Column<ByClient>[] = [
    {
      key: 'client',
      header: 'Client',
      cell: (c) =>
        c.id ? (
          <Link to="/clients/$clientId" params={{ clientId: c.id }} className="font-medium text-heading hover:underline">
            {c.name}
          </Link>
        ) : (
          c.name
        ),
    },
    ...shownMetrics.map<Column<ByClient>>((m, i) => ({
      key: m.key,
      header: m.label,
      align: 'right',
      priority: i < 2 ? 1 : 3,
      cell: (c) => count(c[m.key]),
    })),
  ]
  const waitingCols: Column<OpenWork>[] = [
    { key: 'client', header: 'Client', cell: (c) => <span className="font-medium text-heading">{c.name}</span> },
    {
      key: 'unresolved',
      header: 'Rows to place',
      align: 'right',
      cell: (c) =>
        c.unresolved ? (
          <Link to="/clients/$clientId/review" params={{ clientId: c.id }} search={{ stage: 'unresolved' }} className="text-accent-foreground underline">
            {c.unresolved}
          </Link>
        ) : (
          count(0)
        ),
    },
    {
      key: 'pending',
      header: 'Ready to approve',
      align: 'right',
      cell: (c) =>
        c.pending_approval ? (
          <Link to="/clients/$clientId/review" params={{ clientId: c.id }} search={{ stage: 'pending_approval' }} className="text-link underline">
            {c.pending_approval}
          </Link>
        ) : (
          count(0)
        ),
    },
  ]

  return (
    <div className="grid gap-6 [&>*]:min-w-0" aria-live="polite">
      {heading && (
        <h2 className="text-lg font-semibold text-heading">
          {w.member.name}
          <span className="ml-2 text-sm font-normal text-muted-foreground">{w.member.role_display}</span>
        </h2>
      )}

      <section aria-labelledby="w-done" className="grid gap-3">
        <h3 id="w-done" className="text-[15px] font-semibold text-heading">
          Done, <span className="num">{formatDate(w.period.from)}</span> to <span className="num">{formatDate(w.period.to)}</span>
        </h3>
        <StatGrid>
          {w.metrics.map((m) => (
            <StatCard key={m.key} label={m.label} value={w.totals[m.key]} />
          ))}
        </StatGrid>
        <p className="text-[13px] text-muted-foreground">Worked on {plural(activeDays, 'day')} in this period.</p>
        <DailyActivity days={w.by_day} activeDays={activeDays} />
      </section>

      <section aria-labelledby="w-clients" className="grid gap-3">
        <h3 id="w-clients" className="text-[15px] font-semibold text-heading">
          By client
        </h3>
        {shownMetrics.length === 0 ? (
          <p className="text-sm text-muted-foreground">No recorded work in this period.</p>
        ) : (
          <DataTable caption="Work by client in the period" columns={byClient} rows={w.by_client} rowKey={(c) => c.id ?? 'deleted'} />
        )}
      </section>

      <section aria-labelledby="w-waiting" className="grid gap-3">
        <h3 id="w-waiting" className="text-[15px] font-semibold text-heading">
          Waiting now, on the clients they are on
        </h3>
        {!waiting.length ? (
          <p className="text-sm text-muted-foreground">Nothing is waiting on the clients this person can open.</p>
        ) : (
          <DataTable caption="Open work on this person’s clients" columns={waitingCols} rows={waiting} rowKey={(c) => c.id} />
        )}
        <p className="text-[13px] text-muted-foreground">
          “Rows to place” have no ledger yet. “Ready to approve” have a ledger and wait for a Senior CA.
        </p>
      </section>
    </div>
  )
}

/** Bars for the eye, a table for everyone else: the same numbers, one day per row. */
function DailyActivity({ days, activeDays }: { days: MemberWork['by_day']; activeDays: number }) {
  const peak = Math.max(1, ...days.map((d) => d.count))
  const actions = days.reduce((sum, d) => sum + d.count, 0)
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="mb-2 text-[13px] font-medium text-heading">Daily activity</div>
      <div role="img" aria-label={`Daily activity: ${actions} recorded actions across ${activeDays} days`} className="flex h-24 items-end gap-1">
        {days.map((day) => (
          <div key={day.date} className="flex h-full flex-1 items-end" title={`${formatDate(day.date)} · ${day.count} actions`}>
            <span className={cn('w-full rounded-t-sm', day.count ? 'bg-primary/70' : 'bg-muted')} style={{ height: `${day.count ? Math.max(8, (day.count / peak) * 100) : 3}%` }} />
          </div>
        ))}
      </div>
      <div className="num mt-1 flex justify-between text-xs text-muted-foreground">
        <span>{days[0] ? formatDate(days[0].date) : ''}</span>
        <span>{days.at(-1) ? formatDate(days.at(-1)!.date) : ''}</span>
      </div>
      <details className="mt-2 text-sm">
        <summary className="cursor-pointer text-[13px] text-link underline">Show as a table</summary>
        <div className="mt-2 max-h-64 overflow-auto rounded-md border">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Recorded actions by day</caption>
            <thead className="sticky top-0 bg-surface-2 text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-3 py-1.5 font-semibold">Date</th>
                <th scope="col" className="px-3 py-1.5 text-right font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {days.map((d) => (
                <tr key={d.date} className="border-t">
                  <td className="num px-3 py-1">{formatDate(d.date)}</td>
                  <td className="num px-3 py-1 text-right">{count(d.count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  )
}
