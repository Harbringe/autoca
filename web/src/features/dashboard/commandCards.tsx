// The blocks of the firm command view: a strip of headline tiles, the pipeline of every client's books, client health as a ring,
// the work waiting on each client as columns, the people list, the priority list and the recent activity.
//
// Everything is read from data the server already sends and counted by the definitions in lib/dashboard.ts, so a number here is
// the same number on every other screen. Nothing is invented: where the API has no figure the block is simply not drawn.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { AlertTriangle, Briefcase, CalendarClock, CheckCircle2, Eye, FileCheck2, TrendingUp, Users } from 'lucide-react'
import { useMemo } from 'react'
import { firmPeople, workFlow } from '@/api/queries/dashboard'
import { auditLog } from '@/api/queries/audit'
import { DashCard } from '@/components/ca/DashCard'
import { FigureTile } from '@/components/ca/FigureTile'
import { CountColumns, ColumnsSkeleton } from '@/components/charts/CountColumns'
import { HealthDonut, HealthSkeleton } from '@/components/charts/HealthDonut'
import { PipelineBar, PipelineSkeleton } from '@/components/charts/PipelineBar'
import { RowsSkeleton } from '@/components/charts/StackedRows'
import { GrowFill } from '@/components/charts/ProgressBar'
import { segmentStyle } from '@/components/charts/StackedBar'
import {
  booksInReview,
  clientHealth,
  dueWithin,
  groupAttention,
  healthCounts,
  lateNote,
  sealingFigures,
  standingContext,
  workWaiting,
} from '@/lib/dashboard'
import { formatDate, formatDateTime, plural } from '@/lib/format'
import { nextTarget, STAGES, STAGE_LABEL } from '@/lib/overview'
import { pct } from '@/lib/pct'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import type { CardProps } from './cards'

// --- the strip -------------------------------------------------------------------------------------------------------

/** Entries finished in the last 12 weeks, with the weekly series and the change from the 12 before. */
function FinishedTile() {
  const q = useQuery(workFlow())
  const f = q.data
  const values = f?.weekly.map((w) => w.finished) ?? []
  const diff = f ? f.totals.finished - f.totals.prev_finished : 0
  return (
    <FigureTile
      icon={TrendingUp}
      loading={q.isLoading}
      label="Entries finished"
      value={f ? f.totals.finished : '—'}
      caption={f ? `Last ${f.weekly.length} weeks` : 'Not available'}
      spark={f && values.length >= 2 ? { values, label: `Entries finished each week for ${values.length} weeks` } : undefined}
      delta={
        f && f.totals.prev_finished > 0
          ? { direction: diff > 0 ? 'up' : diff < 0 ? 'down' : 'flat', text: diff === 0 ? 'same' : `${Math.abs(diff)} ${diff > 0 ? 'more' : 'fewer'}`, good: diff > 0 ? true : null }
          : undefined
      }
    />
  )
}

/** Six tiles for the owner: how many clients, what waits, what is in review, what falls due, what is late, what got done. */
export function OwnerStrip({ data, state, today }: CardProps & { today: Date }) {
  const loading = state === 'loading'
  const h = data ? healthCounts(data.clients, standingContext(data, today)) : undefined
  const due = data ? dueWithin(data.deadlines, 30, today).filter((d) => d.date >= formatIso(today)).length : 0
  const waiting = data ? workWaiting(data.totals) : 0
  const review = data ? booksInReview(data.totals) : 0
  return (
    <div className="@container"><div className="grid grid-cols-2 gap-3 @2xl:grid-cols-3 @5xl:grid-cols-6">
      <FigureTile icon={Users} loading={loading} label="Clients" value={data?.clients.length ?? 0} caption={`${data?.by_stage.signed_off ?? 0} fully signed off`} to="/clients" />
      <FigureTile icon={Briefcase} loading={loading} label="Work waiting" value={waiting} caption="Entries to sort, record or check" tone={waiting ? 'watch' : 'plain'} to="/pipeline" />
      <FigureTile icon={Eye} loading={loading} label="Books in review" value={review} caption="Waiting for a senior's decision" to="/pipeline" />
      <FigureTile icon={CalendarClock} loading={loading} label="Compliance due" value={due} caption="Dates in the next 30 days" />
      <FigureTile icon={AlertTriangle} loading={loading} label="Late" value={h?.overdue ?? 0} unit={h ? `of ${h.total}` : undefined} caption={h ? lateNote(h) : undefined} tone={h?.overdue ? 'bad' : 'plain'} to="/alerts" />
      <FinishedTile />
    </div></div>
  )
}

/** Six tiles for a Senior CA: what needs their sign-off first. */
export function SeniorStrip({ data, state, today }: CardProps & { today: Date }) {
  const loading = state === 'loading'
  const clients = data?.clients ?? []
  const seal = sealingFigures(clients)
  const waitingOnMe = seal.waitingForApproval || clients.filter((c) => c.review_pending).length
  const h = data ? healthCounts(clients, standingContext(data, today)) : undefined
  const due = data ? dueWithin(data.deadlines, 30, today).filter((d) => d.date >= formatIso(today)).length : 0
  return (
    <div className="@container"><div className="grid grid-cols-2 gap-3 @2xl:grid-cols-3 @5xl:grid-cols-6">
      <FigureTile
        icon={Eye}
        loading={loading}
        label="Waiting for my approval"
        value={waitingOnMe}
        caption={waitingOnMe && seal.oldestDays ? `Oldest has waited ${plural(seal.oldestDays, 'day')}` : 'Books sent to me'}
        tone={waitingOnMe ? 'watch' : 'plain'}
        to="/pipeline"
      />
      <FigureTile icon={FileCheck2} loading={loading} label="Ready to seal" value={seal.readyToSeal} caption="Approved, nothing changed since" to="/alerts" />
      <FigureTile icon={Briefcase} loading={loading} label="Work waiting" value={data ? workWaiting(data.totals) : 0} caption="Entries to sort, record or check" to="/pipeline" />
      <FigureTile icon={CalendarClock} loading={loading} label="Compliance due" value={due} caption="Dates in the next 30 days" />
      <FigureTile
        icon={AlertTriangle}
        loading={loading}
        label="At risk or late"
        value={h ? h.atRisk + h.overdue : 0}
        unit={h ? `of ${h.total}` : undefined}
        caption={h ? `${h.overdue} late, ${h.atRisk} at risk` : undefined}
        tone={h?.overdue ? 'bad' : h?.atRisk ? 'watch' : 'plain'}
        to="/alerts"
      />
      <FinishedTile />
    </div></div>
  )
}

function formatIso(d: Date) {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

// --- pipeline and health ---------------------------------------------------------------------------------------------

const STAGE_TONE_BAR = {
  no_statements: 'context',
  needs_ledger: 'watch',
  ready_to_post: 'part3',
  ready_for_review: 'part2',
  in_review: 'part1',
  signed_off: 'good',
} as const

/** "Where are my clients' books?": every stage as a number and one segmented bar, in the order the work flows. */
export function PipelineCard({ data, state, title = "Where are my clients' books?" }: CardProps & { title?: string }) {
  const stages = STAGES.map((s) => ({
    key: s,
    label: STAGE_LABEL[s],
    count: data?.by_stage[s] ?? 0,
    tone: STAGE_TONE_BAR[s],
    to: '/clients',
    search: { stage: s } as Record<string, unknown>,
  }))
  const total = stages.reduce((n, s) => n + s.count, 0)
  return (
    <DashCard title={title} state={total === 0 && state === 'ready' ? 'empty' : state} empty="No clients yet. Add a client and upload its bank statement." skeleton="h-28" skeletonShape={<PipelineSkeleton />}>
      <PipelineBar stages={stages} unit="clients" ariaLabel={`${total} clients by stage of their books`} caption="Clients by stage of their books" />
    </DashCard>
  )
}

/** "How healthy are my clients?": a small ring, on track / at risk / late, with the firm's own definitions. */
export function HealthCard({ data, state, today }: CardProps & { today: Date }) {
  const h = data ? healthCounts(data.clients, standingContext(data, today)) : undefined
  return (
    <DashCard
      title="How healthy are my clients?"
      state={state === 'ready' && h && h.total === 0 ? 'empty' : state}
      empty="No clients yet."
      skeleton="h-36"
      skeletonShape={<HealthSkeleton />}
    >
      {h && (
        <HealthDonut
          centerLabel="clients"
          ariaLabel={`${h.onTrack} of ${h.total} clients on track, ${h.atRisk} at risk, ${h.overdue} late`}
          caption="Clients by standing"
          parts={[
            { key: 'good', label: 'On track', count: h.onTrack, to: '/clients' },
            { key: 'watch', label: 'At risk', count: h.atRisk, to: '/alerts' },
            { key: 'bad', label: 'Late', count: h.overdue, to: '/alerts' },
          ]}
        />
      )}
    </DashCard>
  )
}

// --- work by client --------------------------------------------------------------------------------------------------

/** "Where is the work waiting?": one column per client, split into the three kinds of entry that make up work waiting. */
export function WorkColumnsCard({ data, state }: CardProps) {
  const rows = useMemo(
    () =>
      (data?.clients ?? [])
        .map((c) => ({ c, total: workWaiting(c) }))
        .filter((r) => r.total > 0)
        .sort((a, b) => b.total - a.total || a.c.name.localeCompare(b.c.name)),
    [data],
  )
  const shown = rows.slice(0, 8)
  return (
    <DashCard
      title="Where is the work waiting?"
      state={state === 'ready' && rows.length === 0 ? 'empty' : state}
      empty="No entry is waiting on any client."
      to={rows.length > shown.length ? '/pipeline' : undefined}
      seeAll={`See all ${rows.length}`}
      skeleton="h-48"
      skeletonShape={<ColumnsSkeleton />}
    >
      <CountColumns
        ariaLabel={`Work waiting on ${plural(rows.length, 'client')}`}
        caption="Entries waiting, by client and kind"
        columns={shown.map(({ c }) => {
          const target = nextTarget(c.next_step.code)
          return {
            key: c.id,
            label: c.name,
            parts: [
              { name: 'To sort', value: c.unresolved, tone: 'watch' as const },
              { name: 'To record', value: c.pending_approval, tone: 'focus' as const },
              { name: 'To check', value: c.ai_unchecked, tone: 'context' as const },
            ],
            to: target.to,
            params: { clientId: c.id },
            search: target.search as Record<string, unknown> | undefined,
          }
        })}
      />
    </DashCard>
  )
}

// --- priority work ---------------------------------------------------------------------------------------------------

/** "What needs me first?": one row per client with something wrong: what, which client, who leads it, when it is due. */
export function PriorityCard({ data, state, today }: CardProps & { today: Date }) {
  const rows = useMemo(() => {
    const groups = groupAttention(data?.attention ?? [], 6)
    const lead = new Map((data?.clients ?? []).map((c) => [c.id, c.lead?.name ?? null]))
    const iso = formatIso(today)
    const ctx = standingContext(data, today)
    const byId = new Map((data?.clients ?? []).map((c) => [c.id, c]))
    return groups.map((g) => {
      const due = (data?.deadlines ?? []).filter((d) => d.date >= iso && d.clients.includes(g.client)).sort((a, b) => a.date.localeCompare(b.date))[0]
      const c = byId.get(g.clientId)
      const h = c ? clientHealth(c, ctx) : undefined
      return { g, who: lead.get(g.clientId) ?? null, due: due?.date ?? null, dueLabel: due?.label ?? null, health: h?.health ?? 'on_track', why: h?.reasons[0] ?? null }
    })
  }, [data, today])
  return (
    <DashCard
      title="What needs me first?"
      state={state === 'ready' && rows.length === 0 ? 'empty' : state}
      empty="Nothing needs attention. Good."
      to="/alerts"
      seeAll="All alerts"
      skeleton="h-48"
      skeletonShape={<RowsSkeleton rows={4} />}
    >
      <ul className="grid min-w-0 gap-2">
        {rows.map(({ g, who, due, dueLabel, health, why }) => {
          const late = health === 'overdue' || g.critical > 0
          const risk = !late && health === 'at_risk'
          return (
            <li key={g.clientId} className="min-w-0">
              <Link
                to={g.to as never}
                search={g.search as never}
                className={cn('flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-md border-l-[3px] bg-surface-2 py-2 pl-3 pr-3 hover:bg-hover', late ? 'border-l-destructive' : risk ? 'border-l-accent-foreground' : 'border-l-[var(--faint)]')}
              >
                <span className="min-w-0 flex-1 basis-56">
                  <span className="block truncate text-sm font-medium text-heading" title={g.text}>
                    {g.text}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {g.client} · {who ?? 'No Senior CA'}
                    {due ? ` · ${dueLabel} ${formatDate(due)}` : why ? ` · ${why}` : ''}
                    {g.others > 0 ? ` · and ${g.others} more` : ''}
                  </span>
                </span>
                <span
                  className={cn(
                    'inline-flex shrink-0 items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium',
                    late ? 'border-destructive/40 bg-destructive-bg text-destructive' : risk ? 'border-accent-edge bg-accent text-accent-foreground' : 'bg-muted text-muted-foreground',
                  )}
                >
                  {late || risk ? <AlertTriangle className="size-3" aria-hidden /> : <CheckCircle2 className="size-3" aria-hidden />}
                  {late ? 'Late' : risk ? 'At risk' : 'To do'}
                </span>
              </Link>
            </li>
          )
        })}
      </ul>
    </DashCard>
  )
}

// --- people ----------------------------------------------------------------------------------------------------------

const ROLE_WORD: Record<string, string> = { FIRM_ADMIN: 'Firm owner', SENIOR_CA: 'Senior CA', STAFF: 'Staff', READ_ONLY: 'Read only' }

export const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join('') || '?'

/** "How is the team doing?": one line per person, in name order: avatar, role, share finished and a thin bar by state. */
export function StaffListCard({ title = 'How is the team doing?' }: { title?: string }) {
  const q = useQuery(firmPeople())
  // Name order, on purpose: the order never says who did more.
  const rows = useMemo(() => [...(q.data?.people ?? [])].sort((a, b) => a.name.localeCompare(b.name)), [q.data])
  const detailed = q.data?.detailed ?? true
  return (
    <DashCard
      title={title}
      state={q.isLoading ? 'loading' : q.error ? 'error' : rows.length === 0 ? 'empty' : 'ready'}
      error={q.error}
      onRetry={() => void q.refetch()}
      empty="Nobody has been added to your team yet."
      to="/staff"
      seeAll="View all"
      skeleton="h-48"
      skeletonShape={<RowsSkeleton rows={4} />}
    >
      <ul className="grid gap-3">
        {rows.map((p) => {
          const total = p.finished_in_period + p.open_items
          const share = pct(p.finished_in_period, total)
          const late = detailed && p.overdue > 0
          return (
            <li key={p.member_id} className="min-w-0">
              <Link to="/staff" search={{ member: p.member_id } as never} className="block min-w-0 rounded-md px-2 -mx-2 py-1 hover:bg-hover">
                <span className="flex min-w-0 items-center gap-3">
                  <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted text-xs font-semibold text-heading" aria-hidden>
                    {initials(p.name)}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-heading" title={p.name}>
                    {p.name} <span className="text-xs font-normal text-muted-foreground">{ROLE_WORD[p.role] ?? p.role}</span>
                  </span>
                  {late && (
                    <span className="inline-flex shrink-0 items-center gap-1 rounded-sm bg-destructive-bg px-1.5 text-xs font-medium text-destructive">
                      <AlertTriangle className="size-3" aria-hidden /> {p.overdue} late
                    </span>
                  )}
                  <span className="num w-12 shrink-0 text-right text-sm font-semibold text-heading">{total === 0 ? '—' : `${share}%`}</span>
                </span>
                <span
                  role="progressbar"
                  aria-label={`${p.name}: ${p.finished_in_period} finished, ${p.open_items} open`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={share}
                  className="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-muted"
                >
                  <GrowFill id={`person-${p.name}`} percent={share} className="rounded-full" style={segmentStyle(late ? 'watch' : 'good')} />
                </span>
              </Link>
            </li>
          )
        })}
      </ul>
      <p className="mt-3 text-xs text-muted-foreground">In name order. Share = finished this month of finished plus open.</p>
    </DashCard>
  )
}

// --- activity --------------------------------------------------------------------------------------------------------

/** "What just happened?": the newest entries of the firm's activity log. Administrators only (the log is theirs). */
/**
 * The log stores some requests as "POST /api/v1/clients/<id>/invoices/upload/". Say them as words: drop the verb, the version
 * and any identifiers, and name the thing: "Invoices: upload". Sentences the server already wrote are left alone.
 */
export function friendlyAction(action: string): string {
  const m = /^(?:GET|POST|PUT|PATCH|DELETE)\s+\/api\/v\d+\/(.+?)\/?$/.exec(action)
  if (!m) return action
  const parts = m[1]!
    .split('/')
    .filter((p) => p && !/^[0-9a-f]{8}-[0-9a-f]{4}-/i.test(p) && !/^\d+$/.test(p) && p !== 'clients')
    .map((p) => p.replace(/[-_]/g, ' '))
  if (parts.length === 0) return 'Changed something'
  const [first, ...rest] = parts
  return `${first![0]!.toUpperCase()}${first!.slice(1)}${rest.length ? `: ${rest.join(' ')}` : ''}`
}

export function ActivityCard() {
  const { can } = useSession()
  const q = useQuery({ ...auditLog(1, false), enabled: can('audit.view') })
  if (!can('audit.view')) return null
  const rows = (q.data?.results ?? []).slice(0, 6)
  return (
    <DashCard
      title="What just happened?"
      state={q.isLoading ? 'loading' : q.error ? 'error' : rows.length === 0 ? 'empty' : 'ready'}
      error={q.error}
      onRetry={() => void q.refetch()}
      empty="Nothing has been recorded yet."
      to="/settings/activity"
      seeAll="Activity log"
      skeleton="h-48"
      skeletonShape={<RowsSkeleton rows={5} />}
    >
      <ul className="divide-y">
        {rows.map((r) => (
          <li key={r.id} className="flex items-start gap-3 py-2 first:pt-0 last:pb-0">
            <span className={cn('mt-1.5 size-2 shrink-0 rounded-full', r.succeeded ? 'bg-[var(--chart-1)]' : 'bg-destructive')} aria-hidden />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm text-heading" title={r.action}>
                {friendlyAction(r.action)}
                {!r.succeeded && <span className="ml-1.5 text-xs font-medium text-destructive">refused</span>}
              </span>
              <span className="block truncate text-xs text-muted-foreground">
                {r.who} · <span className="num">{formatDateTime(r.at)}</span>
              </span>
            </span>
          </li>
        ))}
      </ul>
    </DashCard>
  )
}

