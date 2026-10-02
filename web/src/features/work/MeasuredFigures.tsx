// The measured figures for a period: how much of the posting the assistant did without a person,
// how often its placements stood, an estimate of the time that saved, which clients need a look and
// why, and how long statements and sign-offs took per person.
//
// Every figure comes from GET /firm/metrics/. A ratio the server could not compute is null and is
// said in words, never 0% or NaN. The time saved is always labelled an estimate. People are listed
// alphabetically and nothing is scored or ranked. Only administrators and Senior CAs may ask; for
// anyone else (a 403) nothing is drawn at all.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useMemo, useState } from 'react'
import { isApiError } from '@/api/errors'
import { firmMetrics } from '@/api/queries/metrics'
import type { FirmMetrics, MetricsTurnaround } from '@/api/types'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { StatCard, StatGrid } from '@/components/ui/stat-card'
import { DataTable, type Column } from '@/components/ui/table'
import { formatDate, plural } from '@/lib/format'
import { attentionClients, daysText, estimateNote, minutesText, NOT_ENOUGH_DATA, percentText, turnaroundByName } from '@/lib/metrics'
import { rangeFor, type PeriodKey, type Range } from '@/lib/period'
import { useSession } from '@/session/session'
import { PeriodPicker } from './PeriodPicker'

/** The caveat the server attaches to the accuracy figure (its schema description), in short. */
export const ACCURACY_CAVEAT = 'Accuracy errs high: stored data cannot show a rule placement that a person overrode before posting.'

const nil = <span className="text-faint">–</span>

export function MeasuredFigures({ range, title = 'Measured figures' }: { range: Range; title?: string }) {
  const { can } = useSession()
  const metrics = useQuery({ ...firmMetrics(range), enabled: can('team.view'), refetchInterval: 30_000, refetchIntervalInBackground: false })

  if (!can('team.view')) return null
  // The server says no to roles it does not serve; that is "not for you", not an error to show.
  if (isApiError(metrics.error) && metrics.error.status === 403) return null

  return (
    <section aria-labelledby="measured" className="grid gap-4">
      <div>
        <h2 id="measured" className="text-[15px] font-semibold text-heading">
          {title}
        </h2>
        <p className="text-[13px] text-muted-foreground">
          From the books and the audit trail, <span className="num">{formatDate(range.from)}</span> to <span className="num">{formatDate(range.to)}</span>. Counts and medians only: nothing is scored or ranked.
        </p>
      </div>
      {metrics.error ? (
        <ErrorState error={metrics.error} retry={() => void metrics.refetch()} />
      ) : metrics.isLoading || !metrics.data ? (
        <div aria-busy="true" className="grid gap-3">
          <span className="sr-only">Loading the measured figures</span>
          <StatGrid aria-hidden>
            {Array.from({ length: 4 }, (_, i) => (
              <div key={i} className="skeleton h-24 rounded-lg" />
            ))}
          </StatGrid>
        </div>
      ) : (
        <Loaded data={metrics.data} />
      )}
    </section>
  )
}

function Loaded({ data }: { data: FirmMetrics }) {
  const f = data.firm
  const automation = percentText(f.automation_share)
  const accuracy = percentText(f.accuracy)
  const attention = useMemo(() => attentionClients(data), [data])
  const people = useMemo(() => turnaroundByName(data), [data])

  return (
    <div className="grid gap-6 [&>*]:min-w-0">
      <div className="grid gap-2">
        <StatGrid>
          <StatCard
            label="Automation share"
            value={automation ?? <span className="text-base font-medium text-muted-foreground">{NOT_ENOUGH_DATA}</span>}
            note={automation ? `${f.rows_automated} of ${plural(f.rows_posted, 'posted row')} were placed and posted by the assistant, unchanged` : 'No row reached the books in this period.'}
          />
          <StatCard
            label="Accuracy"
            value={accuracy ?? <span className="text-base font-medium text-muted-foreground">{NOT_ENOUGH_DATA}</span>}
            note={accuracy ? `${f.placements_stayed} stood, ${f.placements_changed} changed` : 'No rule or model placement to judge yet.'}
          />
          <StatCard
            label="Estimated time saved"
            value={f.rows_posted > 0 ? minutesText(f.estimated_minutes_saved) : <span className="text-base font-medium text-muted-foreground">{NOT_ENOUGH_DATA}</span>}
            note={`${estimateNote(data.assumed_minutes_per_row)}. Not a measurement.`}
          />
          <StatCard
            label="Clients that need attention"
            value={f.clients_needing_attention}
            note={`of ${plural(f.clients, 'client')}, as the books stand now`}
            tone={f.clients_needing_attention ? 'attention' : 'plain'}
          />
        </StatGrid>
        <p className="max-w-3xl text-[13px] text-muted-foreground">{ACCURACY_CAVEAT}</p>
      </div>

      <section aria-labelledby="needs-look" className="grid gap-2">
        <h3 id="needs-look" className="text-sm font-semibold text-heading">
          Clients that need attention
        </h3>
        {attention.length === 0 ? (
          <p className="text-sm text-muted-foreground">No client needs attention right now.</p>
        ) : (
          <ul className="divide-y rounded-lg border bg-card text-sm">
            {attention.map((c) => (
              <li key={c.id} className="grid gap-1 px-4 py-2.5 sm:grid-cols-[minmax(0,16rem)_minmax(0,1fr)] sm:gap-x-4">
                <Link to="/clients/$clientId" params={{ clientId: c.id }} className="truncate font-medium text-heading hover:underline" title={c.name}>
                  {c.name}
                </Link>
                <ul className="grid gap-0.5 text-muted-foreground">
                  {c.needs_attention.map((reason) => (
                    <li key={reason.code}>{reason.message}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="turnaround" className="grid gap-2">
        <div>
          <h3 id="turnaround" className="text-sm font-semibold text-heading">
            Turnaround per person
          </h3>
          <p className="text-[13px] text-muted-foreground">Medians of elapsed days, not working time. In alphabetical order.</p>
        </div>
        <Turnaround rows={people} />
      </section>
    </div>
  )
}

function Turnaround({ rows }: { rows: MetricsTurnaround[] }) {
  const columns: Column<MetricsTurnaround>[] = [
    { key: 'person', header: 'Person', cell: (t) => <span className="font-medium text-heading">{t.member.name}</span> },
    { key: 'done', header: 'Statements completed', align: 'right', priority: 2, cell: (t) => (t.statements_completed ? t.statements_completed : nil) },
    { key: 'posted', header: 'Median days, upload to posted', align: 'right', cell: (t) => <Days n={t.median_days_upload_to_posted} /> },
    { key: 'signed', header: 'Books signed off', align: 'right', priority: 2, cell: (t) => (t.books_signed_off ? t.books_signed_off : nil) },
    { key: 'review', header: 'Median days, request to sign-off', align: 'right', priority: 3, cell: (t) => <Days n={t.median_days_request_to_sign_off} /> },
  ]
  return (
    <DataTable
      caption="Turnaround per person in the period"
      columns={columns}
      rows={rows}
      rowKey={(t) => t.member.id}
      empty={<EmptyState title="Nothing finished in this period">No statement was completed and no books were signed off by anyone.</EmptyState>}
    />
  )
}

function Days({ n }: { n: number | null }) {
  return n === null ? <span className="text-muted-foreground">{NOT_ENOUGH_DATA}</span> : <span>{daysText(n)}</span>
}

/** "This period" on the Dashboard: its own period choice, kept in the page, over the same figures. */
export function ThisPeriod() {
  const { can } = useSession()
  const [pick, setPick] = useState<{ key: PeriodKey; from?: string; to?: string }>({ key: 'month' })
  const range = useMemo(() => rangeFor(pick.key, pick.from, pick.to), [pick])
  if (!can('team.view')) return null
  return (
    <div className="grid gap-3">
      <PeriodPicker key={`${pick.key}${pick.from}${pick.to}`} value={pick.key} range={range} onPick={(next) => setPick({ key: next.period, from: next.from, to: next.to })} />
      {range && <MeasuredFigures range={range} title="This period" />}
    </div>
  )
}
