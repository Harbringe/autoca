// Work & performance: what people did in a period, and what is waiting on them now.
//
// Counts only, in the order people are named: nobody is ranked, scored or compared. A firm
// administrator sees everyone; a Senior CA their team; everyone else only their own work. What is
// "waiting now" is not history, so it does not change with the period.

import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useMemo, useState, type FormEvent } from 'react'
import { memberWork, teamClients, teamMembers } from '@/api/queries/team'
import type { Metric, MetricKey } from '@/api/types'
import { EmptyState, ErrorState, PageHeader } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { tbl } from '@/components/ui/controls'
import { DateInput } from '@/components/ui/date-input'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, parseDate, plural } from '@/lib/format'
import { PERIOD_LABEL, presetRange, rangeProblem, type PeriodKey, type Range } from '@/lib/period'
import { usePageTitle } from '@/lib/title'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'

const PRESETS: PeriodKey[] = ['month', 'last', 'fy', 'custom']

export interface WorkSearch {
  period?: PeriodKey
  from?: string
  to?: string
  member?: string
}

export function WorkScreen({ search }: { search: WorkSearch }) {
  const { can, me } = useSession()
  const navigate = useNavigate({ from: '/work' })
  const firmView = can('team.view')
  usePageTitle(firmView ? 'Work & performance' : 'My work')

  const key: PeriodKey = search.period ?? 'month'
  const range: Range | null = useMemo(() => {
    if (key !== 'custom') return presetRange(key, new Date())
    return search.from && search.to ? { from: search.from, to: search.to } : null
  }, [key, search.from, search.to])

  const memberId = (firmView ? search.member : undefined) ?? me?.membership_id ?? undefined
  const go = (next: { period?: PeriodKey; from?: string; to?: string; member?: string }) =>
    void navigate({ search: (prev) => ({ ...prev, ...next }), replace: true })

  return (
    <div className="grid gap-8 [&>*]:min-w-0">
      <div>
        <PageHeader
          title={firmView ? 'Work & performance' : 'My work'}
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
          <People range={range} selected={memberId} onSelect={(id) => go({ member: id })} />
          <WaitingOnClients />
        </>
      )}
      {memberId && range && <PersonWork memberId={memberId} range={range} heading={firmView} />}
      {!memberId && !firmView && <EmptyState title="Nothing to show">Your work appears here once you are on a firm.</EmptyState>}
    </div>
  )
}

function PeriodPicker({
  value,
  range,
  onPick,
}: {
  value: PeriodKey
  range: Range | null
  onPick: (next: { period: PeriodKey; from?: string; to?: string }) => void
}) {
  const [from, setFrom] = useState(range ? formatDate(range.from) : '')
  const [to, setTo] = useState(range ? formatDate(range.to) : '')
  const [error, setError] = useState<string | null>(null)

  function apply(e: FormEvent) {
    e.preventDefault()
    const f = parseDate(from)
    const t = parseDate(to)
    const problem = rangeProblem(f && t ? { from: f, to: t } : null)
    setError(problem)
    if (!problem) onPick({ period: 'custom', from: f!, to: t! })
  }

  return (
    <div className="grid gap-2">
      <div role="group" aria-label="Period" className="flex flex-wrap gap-1.5">
        {PRESETS.map((p) => (
          <Button
            key={p}
            size="sm"
            variant={p === value ? 'primary' : 'outline'}
            aria-pressed={p === value}
            onClick={() => (p === 'custom' ? onPick({ period: 'custom', from: range?.from, to: range?.to }) : onPick({ period: p, from: undefined, to: undefined }))}
          >
            {PERIOD_LABEL[p]}
          </Button>
        ))}
      </div>
      {value === 'custom' && (
        <form onSubmit={apply} className="flex flex-wrap items-start gap-2" noValidate>
          <label className="grid gap-1 text-[13px] text-muted-foreground">
            From
            <DateInput aria-invalid={!!error} className="w-36" value={from} onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label className="grid gap-1 text-[13px] text-muted-foreground">
            To
            <DateInput aria-invalid={!!error} className="w-36" value={to} onChange={(e) => setTo(e.target.value)} />
          </label>
          <Button type="submit" size="md" className="mt-5">
            Show
          </Button>
          {error && (
            <p role="alert" className="mt-5 text-sm text-destructive">
              {error}
            </p>
          )}
        </form>
      )}
      {range && (
        <p className="text-[13px] text-muted-foreground">
          <span className="num">{formatDate(range.from)}</span> to <span className="num">{formatDate(range.to)}</span>
        </p>
      )}
    </div>
  )
}

const count = (n: number) => (n === 0 ? <span className="text-muted-foreground">0</span> : n)

function People({ range, selected, onSelect }: { range: Range; selected?: string; onSelect: (id: string) => void }) {
  const members = useQuery(teamMembers(range))
  if (members.isPending) return <Spinner label="Adding up the work…" />
  if (members.error) return <ErrorState error={members.error} retry={() => void members.refetch()} />
  const { metrics, results } = members.data
  // Alphabetical, on purpose: the order never says who did more.
  const people = [...results].sort((a, b) => a.name.localeCompare(b.name))
  const total = (k: MetricKey) => people.reduce((sum, p) => sum + p.work[k], 0)
  return (
    <section aria-labelledby="people-work">
      <h2 id="people-work" className="mb-2 text-base font-semibold">
        Done in the period
      </h2>
      <div className={tbl.wrap}>
        <table className={tbl.table}>
          <thead className={tbl.head}>
            <tr>
              <th scope="col" className={tbl.th}>Person</th>
              {metrics.map((m) => (
                <th key={m.key} scope="col" className={cn(tbl.thNum, 'whitespace-normal')}>
                  {m.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {people.map((p) => (
              <tr key={p.id} className={cn(tbl.row, p.id === selected && 'bg-accent/10')} aria-current={p.id === selected ? 'true' : undefined}>
                <td className={tbl.td}>
                  <button
                    type="button"
                    className="text-left font-medium hover:underline"
                    aria-label={`Show ${p.name}’s work in detail`}
                    onClick={() => onSelect(p.id)}
                  >
                    {p.name}
                  </button>
                  <div className="text-[13px] text-muted-foreground">
                    {p.role_display}
                    {!p.is_active && ' · deactivated'}
                  </div>
                </td>
                {metrics.map((m) => (
                  <td key={m.key} className={tbl.tdNum}>
                    {count(p.work[m.key])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          {people.length > 1 && (
            <tfoot className={tbl.foot}>
              <tr className={tbl.row}>
                <th scope="row" className={cn(tbl.td, 'text-left')}>All shown</th>
                {metrics.map((m) => (
                  <td key={m.key} className={tbl.tdNum}>
                    {total(m.key)}
                  </td>
                ))}
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </section>
  )
}

function PersonWork({ memberId, range, heading }: { memberId: string; range: Range; heading: boolean }) {
  const work = useQuery(memberWork(memberId, range))
  if (work.isPending) return <Spinner label="Loading…" />
  if (work.error) return <ErrorState error={work.error} retry={() => void work.refetch()} />
  const w = work.data
  const shownMetrics = w.metrics.filter((m) => w.by_client.some((c) => c[m.key] > 0))
  const activeDays = w.by_day.filter((d) => d.count > 0).length
  const waiting = w.open_work.filter((c) => c.unresolved > 0 || c.pending_approval > 0)

  return (
    <div className="grid gap-6 [&>*]:min-w-0" aria-live="polite">
      {heading && (
        <h2 className="text-lg font-semibold">
          {w.member.name}
          <span className="ml-2 text-sm font-normal text-muted-foreground">{w.member.role_display}</span>
        </h2>
      )}

      <section aria-labelledby="w-done">
        <h3 id="w-done" className="mb-2 text-base font-semibold">
          Done, <span className="num">{formatDate(w.period.from)}</span> to <span className="num">{formatDate(w.period.to)}</span>
        </h3>
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {w.metrics.map((m: Metric) => (
            <div key={m.key} className="rounded-lg border bg-card p-3">
              <dt className="text-[13px] text-muted-foreground">{m.label}</dt>
              <dd className="num mt-0.5 text-2xl font-semibold">{w.totals[m.key]}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-2 text-[13px] text-muted-foreground">Worked on {plural(activeDays, 'day')} in this period.</p>
      </section>

      <section aria-labelledby="w-clients">
        <h3 id="w-clients" className="mb-2 text-base font-semibold">
          By client
        </h3>
        {shownMetrics.length === 0 ? (
          <p className="text-sm text-muted-foreground">No recorded work in this period.</p>
        ) : (
          <div className={tbl.wrap}>
            <table className={tbl.table}>
              <thead className={tbl.head}>
                <tr>
                  <th scope="col" className={tbl.th}>Client</th>
                  {shownMetrics.map((m) => (
                    <th key={m.key} scope="col" className={cn(tbl.thNum, 'whitespace-normal')}>
                      {m.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {w.by_client.map((c) => (
                  <tr key={c.id ?? 'deleted'} className={tbl.row}>
                    <td className={tbl.td}>
                      {c.id ? (
                        <Link to="/clients/$clientId" params={{ clientId: c.id }} className="hover:underline">
                          {c.name}
                        </Link>
                      ) : (
                        c.name
                      )}
                    </td>
                    {shownMetrics.map((m) => (
                      <td key={m.key} className={tbl.tdNum}>
                        {count(c[m.key])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-labelledby="w-waiting">
        <h3 id="w-waiting" className="mb-2 text-base font-semibold">
          Waiting now, on the clients they are on
        </h3>
        {!waiting.length ? (
          <p className="text-sm text-muted-foreground">Nothing is waiting on the clients this person can open.</p>
        ) : (
          <div className={tbl.wrap}>
            <table className={tbl.table}>
              <thead className={tbl.head}>
                <tr>
                  <th scope="col" className={tbl.th}>Client</th>
                  <th scope="col" className={tbl.thNum}>Rows to place</th>
                  <th scope="col" className={tbl.thNum}>Ready to approve</th>
                </tr>
              </thead>
              <tbody>
                {waiting.map((c) => (
                  <tr key={c.id} className={tbl.row}>
                    <td className={tbl.td}>{c.name}</td>
                    <td className={tbl.tdNum}>
                      {c.unresolved ? (
                        <Link to="/clients/$clientId/review" params={{ clientId: c.id }} search={{ stage: 'unresolved' }} className="text-warning hover:underline">
                          {c.unresolved}
                        </Link>
                      ) : (
                        count(0)
                      )}
                    </td>
                    <td className={tbl.tdNum}>
                      {c.pending_approval ? (
                        <Link to="/clients/$clientId/review" params={{ clientId: c.id }} search={{ stage: 'pending_approval' }} className="text-info hover:underline">
                          {c.pending_approval}
                        </Link>
                      ) : (
                        count(0)
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-2 text-[13px] text-muted-foreground">
          “Rows to place” have no ledger yet. “Ready to approve” have a ledger and wait for a Senior CA.
        </p>
      </section>
    </div>
  )
}

/** The firm's open work by client, for whoever manages the clients: where the backlog sits. */
function WaitingOnClients() {
  const clients = useQuery(teamClients())
  if (clients.isPending) return null
  if (clients.error) return <ErrorState error={clients.error} retry={() => void clients.refetch()} />
  const rows = clients.data.results.filter((c) => c.unresolved > 0 || c.pending_approval > 0)
  const idle = clients.data.results.length - rows.length
  return (
    <section aria-labelledby="w-backlog">
      <h2 id="w-backlog" className="mb-2 text-base font-semibold">
        Waiting now, by client
      </h2>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nothing is waiting on any client.</p>
      ) : (
        <div className={tbl.wrap}>
          <table className={tbl.table}>
            <thead className={tbl.head}>
              <tr>
                <th scope="col" className={tbl.th}>Client</th>
                <th scope="col" className={tbl.th}>Senior CA</th>
                <th scope="col" className={tbl.th}>Team</th>
                <th scope="col" className={tbl.thNum}>Rows to place</th>
                <th scope="col" className={tbl.thNum}>Ready to approve</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className={tbl.row}>
                  <td className={tbl.td}>
                    <Link to="/clients/$clientId/team" params={{ clientId: c.id }} className="font-medium hover:underline">
                      {c.name}
                    </Link>
                  </td>
                  <td className={tbl.td}>{c.lead?.name ?? <span className="text-warning">Not assigned</span>}</td>
                  <td className={cn(tbl.td, 'max-w-64 text-[13px] text-muted-foreground')}>{c.team.map((p) => p.name).join(', ') || 'Nobody assigned'}</td>
                  <td className={tbl.tdNum}>{count(c.unresolved)}</td>
                  <td className={tbl.tdNum}>{count(c.pending_approval)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {idle > 0 && <p className="mt-2 text-[13px] text-muted-foreground">{plural(idle, 'other client')} with nothing waiting.</p>}
    </section>
  )
}
