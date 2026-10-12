// The staff page as one card per person: five small count tiles, how much of their work is finished, and a status chip.
//
// Only figures the server has are drawn. Per person it sends: clients assigned, entries finished in the period, open entries,
// entries waiting on someone else and late items (firm/people), and the medians of upload-to-posted and books signed off
// (firm/metrics). It does NOT send a capacity, so there is no workload bar, no "overloaded" and no per-person correction rate;
// those are DATA REQUESTS. People are in name order and nothing ranks or scores them.

import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Circle } from 'lucide-react'
import { useMemo } from 'react'
import { firmPeople } from '@/api/queries/dashboard'
import { firmMetrics } from '@/api/queries/metrics'
import { isApiError } from '@/api/errors'
import type { PersonWork } from '@/api/types'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { GrowFill } from '@/components/charts/ProgressBar'
import { segmentStyle } from '@/components/charts/StackedBar'
import { initials } from '@/features/dashboard/commandCards'
import { pct } from '@/lib/pct'
import { daysText } from '@/lib/metrics'
import { cn } from '@/lib/utils'
import { FigureTile } from '@/components/ca/FigureTile'
import { Briefcase, CheckCheck, Users } from 'lucide-react'
import type { Range } from '@/lib/period'

const ROLE_WORD: Record<string, string> = { FIRM_ADMIN: 'Firm owner', SENIOR_CA: 'Senior CA', STAFF: 'Staff', READ_ONLY: 'Read only' }

export type PersonStatus = 'attention' | 'on_track' | 'idle'

/** Needs attention when something of theirs is late; idle when they have nothing assigned or open; otherwise on track. */
export function personStatus(p: Pick<PersonWork, 'overdue' | 'open_items' | 'finished_in_period' | 'assigned_clients'>, detailed = true): PersonStatus {
  if (detailed && p.overdue > 0) return 'attention'
  if (p.assigned_clients === 0 && p.open_items === 0 && p.finished_in_period === 0) return 'idle'
  return 'on_track'
}

const STATUS = {
  attention: { word: 'Needs attention', icon: AlertTriangle, cls: 'border-accent-edge bg-accent text-accent-foreground', bar: 'watch' as const },
  on_track: { word: 'On track', icon: CheckCircle2, cls: 'border-success/40 bg-success-bg text-success', bar: 'good' as const },
  idle: { word: 'Nothing assigned', icon: Circle, cls: 'bg-muted text-muted-foreground', bar: 'context' as const },
}

function Count({ n, label, hot }: { n: number; label: string; hot?: boolean }) {
  return (
    <div className="rounded-md bg-surface-2 px-2 py-2 text-center">
      <div className={cn('num text-xl font-semibold leading-6', hot ? 'text-destructive' : 'text-heading')}>{n}</div>
      <div className="mt-0.5 truncate text-xs text-muted-foreground" title={label}>
        {label}
      </div>
    </div>
  )
}

export function PersonCard({
  p,
  detailed,
  days,
  signed,
  selected,
  onSelect,
}: {
  p: PersonWork
  detailed: boolean
  /** Median days from upload to posted, when measured. */
  days?: number | null
  /** Books signed off in the period, when measured. */
  signed?: number
  selected?: boolean
  onSelect?: (id: string) => void
}) {
  const status = personStatus(p, detailed)
  const s = STATUS[status]
  const Icon = s.icon
  const total = p.finished_in_period + p.open_items
  const share = pct(p.finished_in_period, total)
  return (
    <article className={cn('rounded-xl border bg-card p-4', selected && 'border-primary ring-1 ring-primary')} aria-label={p.name}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-full bg-muted text-sm font-semibold text-heading" aria-hidden>
            {initials(p.name)}
          </span>
          <div className="min-w-0">
            <h3 className="truncate text-[15px] font-semibold text-heading" title={p.name}>
              {p.name}
            </h3>
            <p className="truncate text-[13px] text-muted-foreground">{ROLE_WORD[p.role] ?? p.role}</p>
          </div>
        </div>
        <span className={cn('inline-flex shrink-0 items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium', s.cls)}>
          <Icon className="size-3" aria-hidden /> {s.word}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-5 gap-1.5 max-sm:grid-cols-3">
        <Count n={p.assigned_clients} label="Clients" />
        <Count n={p.finished_in_period} label="Finished" />
        <Count n={p.open_items} label="Open" />
        <Count n={p.waiting_on_others} label="Waiting" />
        {detailed ? <Count n={p.overdue} label="Late" hot={p.overdue > 0} /> : <Count n={0} label="Late" />}
      </div>

      <div className="mt-3">
        <div className="flex items-baseline justify-between text-xs text-muted-foreground">
          <span>Finished of finished plus open</span>
          <span className="num text-sm font-semibold text-heading">{total === 0 ? '—' : `${share}%`}</span>
        </div>
        <span
          role="progressbar"
          aria-label={`${p.name}: ${p.finished_in_period} finished and ${p.open_items} open`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={share}
          className="mt-1 block h-2 overflow-hidden rounded-full bg-muted"
        >
          <GrowFill id={`person-${p.name}`} percent={share} className="rounded-full" style={segmentStyle(s.bar)} />
        </span>
      </div>

      {(days !== undefined || signed !== undefined) && (
        <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
          {days !== undefined && (
            <div>
              <dt className="inline">Typical time, upload to posted: </dt>
              <dd className="num inline font-medium text-heading">{days === null ? 'not enough data' : daysText(days)}</dd>
            </div>
          )}
          {signed !== undefined && (
            <div>
              <dt className="inline">Books signed off: </dt>
              <dd className="num inline font-medium text-heading">{signed}</dd>
            </div>
          )}
        </dl>
      )}

      {onSelect && (
        <button type="button" onClick={() => onSelect(p.member_id)} aria-pressed={!!selected} className="mt-3 min-h-11 text-[13px] font-medium text-link underline underline-offset-2 sm:min-h-8">
          {selected ? 'Showing their work below' : `Show ${p.name}’s work`}
        </button>
      )}
    </article>
  )
}

/** A card-shaped ghost while loading. */
export function PersonCardsSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2" aria-hidden>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="rounded-xl border bg-card p-4">
          <div className="flex items-center gap-3">
            <span className="skeleton size-10 rounded-full" />
            <span className="skeleton h-4 w-40 rounded" />
          </div>
          <div className="mt-3 grid grid-cols-5 gap-1.5">
            {Array.from({ length: 5 }, (_, j) => (
              <span key={j} className="skeleton h-14 rounded-md" />
            ))}
          </div>
          <span className="skeleton mt-4 block h-2 rounded-full" />
        </div>
      ))}
    </div>
  )
}

/** The team: a strip of totals, then one card per person in name order. Asked only by people who may see a team. */
export function PersonCards({ range, selected, onSelect }: { range: Range; selected?: string; onSelect: (id: string) => void }) {
  const people = useQuery(firmPeople(range))
  const metrics = useQuery({ ...firmMetrics(range), enabled: !!people.data })
  const turnaround = useMemo(() => new Map((metrics.data?.turnaround ?? []).map((t) => [t.member.id, t])), [metrics.data])
  const measured = !!metrics.data && !(isApiError(metrics.error) && metrics.error.status === 403)

  if (people.isLoading) {
    return (
      <div aria-busy="true" className="grid gap-4">
        <span className="sr-only">Adding up the work…</span>
        <PersonCardsSkeleton />
      </div>
    )
  }
  if (people.error) return <ErrorState error={people.error} retry={() => void people.refetch()} />
  const rows = [...(people.data?.people ?? [])].sort((a, b) => a.name.localeCompare(b.name))
  if (rows.length === 0) return <EmptyState title="Nobody on the team yet">People you add to your team appear here, one card each, with what they have on.</EmptyState>
  const detailed = people.data?.detailed ?? true
  const finished = rows.reduce((n, p) => n + p.finished_in_period, 0)
  const open = rows.reduce((n, p) => n + p.open_items, 0)
  const attention = rows.filter((p) => personStatus(p, detailed) === 'attention').length
  return (
    <section aria-label="People" className="grid gap-4">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <FigureTile icon={Users} label="Team members" value={rows.length} caption="With work in this view" />
        <FigureTile icon={Briefcase} label="Work waiting" value={open} caption="Open entries across the team" />
        <FigureTile icon={CheckCheck} label="Finished share" value={`${pct(finished, finished + open)}%`} caption="Finished of finished plus open" tone="good" />
        <FigureTile icon={AlertTriangle} label="Need attention" value={detailed ? attention : '—'} caption={detailed ? 'Someone has a late item' : 'Not worked out for a firm this size'} tone={attention ? 'watch' : 'plain'} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
        {rows.map((p) => {
          const t = turnaround.get(p.member_id)
          return (
            <PersonCard
              key={p.member_id}
              p={p}
              detailed={detailed}
              days={measured && t ? t.median_days_upload_to_posted : undefined}
              signed={measured && t ? t.books_signed_off : undefined}
              selected={selected === p.member_id}
              onSelect={onSelect}
            />
          )
        })}
      </div>
    </section>
  )
}
