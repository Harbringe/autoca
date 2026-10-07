// The cards the three dashboards share, each one question long. They read the firm portfolio the server
// already scopes by role (a Senior CA sees their team's clients, Staff the clients they are on), so the
// same card is right for every layout. Figures are counts of clients and work, never a score for a person.

import { useMemo } from 'react'
import type { Portfolio, PortfolioClient, Stage } from '@/api/types'
import { ActionList } from '@/components/ca/ActionList'
import { DashCard, type CardState } from '@/components/ca/DashCard'
import { DonutLegend } from '@/components/charts/DonutLegend'
import { RankedBars } from '@/components/charts/RankedBars'
import { actionsFor, clientHealth, dueWithin, groupAttention } from '@/lib/dashboard'
import { formatCompact, formatDate, formatPaise, plural } from '@/lib/format'
import { STAGES, STAGE_LABEL } from '@/lib/overview'

/** One colour per stage: the finished state in the main hue, "a person must look" in champagne, the rest stepped. */
const STAGE_COLOR: Record<Stage, string> = {
  no_statements: 'var(--chart-muted)',
  needs_ledger: 'var(--chart-2)',
  ready_to_post: 'var(--chart-seq-4)',
  ready_for_review: 'var(--chart-seq-3)',
  in_review: 'var(--chart-seq-2)',
  signed_off: 'var(--chart-1)',
}

export interface CardProps {
  data: Portfolio | undefined
  state: CardState
}

/** "Where are my clients' books today?": the six stages as a ring and rows, each row opening those clients. */
export function BooksDonutCard({ data, state, title, empty }: CardProps & { title: string; empty: string }) {
  const rows = STAGES.map((stage) => ({
    key: stage,
    label: STAGE_LABEL[stage],
    count: data?.by_stage[stage] ?? 0,
    color: STAGE_COLOR[stage],
    to: '/clients',
    search: { stage },
  }))
  const total = rows.reduce((n, r) => n + r.count, 0)
  const signed = data?.by_stage.signed_off ?? 0
  return (
    <DashCard title={title} hint="Every client sits in one of these places." state={total === 0 && state === 'ready' ? 'empty' : state} empty={empty} skeleton="h-44">
      <DonutLegend
        rows={rows}
        centerValue={total}
        centerLabel={total === 1 ? 'client' : 'clients'}
        summary={`${signed} of ${plural(total, 'client')} fully signed off. ${rows.filter((r) => r.count).map((r) => `${r.label}: ${r.count}`).join('. ')}.`}
        caption="Clients by where their books are"
      />
    </DashCard>
  )
}

/** "Which clients need me first?": one bar per client, as many items as the server has flagged for it. */
export function NeedMeFirstCard({ data, state }: CardProps) {
  const groups = useMemo(() => groupAttention(data?.attention ?? []), [data])
  const flagged = new Set(data?.attention.map((a) => a.client)).size
  return (
    <DashCard
      title="Which clients need me first?"
      hint="Most serious first. The words say what is wrong."
      state={state === 'ready' && groups.length === 0 ? 'empty' : state}
      empty="No client needs attention. Good."
      to="/alerts"
      seeAll={flagged > groups.length ? `See all ${flagged}` : 'See all alerts'}
      skeleton="h-48"
    >
      <RankedBars
        rows={groups.map((g) => ({
          key: g.clientId,
          label: g.client,
          value: g.items,
          valueLabel: g.critical ? `${plural(g.items, 'item')}, ${g.critical} overdue` : plural(g.items, 'item'),
          note: g.others > 0 ? `${g.text} (and ${g.others} more)` : g.text,
          to: g.to,
          search: g.search,
          tone: g.critical ? 'danger' : 'accent',
        }))}
      />
    </DashCard>
  )
}

/** "What falls due in the next 30 days?": the server's dated list (TDS deposits, sealing dates), trimmed to a month. */
export function DueSoonCard({ data, state, today }: CardProps & { today: Date }) {
  const rows = useMemo(() => dueWithin(data?.deadlines ?? [], 30, today), [data, today])
  return (
    <DashCard title="What falls due in the next 30 days?" hint="TDS deposits and sealing dates." state={state === 'ready' && rows.length === 0 ? 'empty' : state} empty="Nothing falls due in the next 30 days." skeleton="h-40">
      <ul className="divide-y">
        {rows.map((d) => (
          <li key={`${d.date}-${d.label}`} className="grid gap-0.5 py-2.5 first:pt-0 last:pb-0">
            <span className="flex items-baseline justify-between gap-3">
              <strong className="text-sm text-heading">{d.label}</strong>
              <span className="num shrink-0 text-[13px] text-muted-foreground">{formatDate(d.date)}</span>
            </span>
            <span className="text-[13px] text-muted-foreground">{d.clients.length > 3 ? `${d.clients.slice(0, 3).join(', ')} and ${d.clients.length - 3} more` : d.clients.join(', ')}</span>
          </li>
        ))}
      </ul>
    </DashCard>
  )
}

/** "How much is owed to my clients, and by them?": the server's firm-wide roll-up, only where it sent money. */
export function OwedCard({ data, state }: CardProps) {
  const receivable = data?.receivables_total_paise
  const payable = data?.payables_total_paise
  const top = data?.top_receivables ?? []
  const aging = data?.aging?.receivables ?? []
  const agingTotal = aging.reduce((n, b) => n + b.amount_paise, 0)
  const present = receivable !== undefined && payable !== undefined
  const missing = state === 'ready' && !present
  const none = state === 'ready' && present && receivable === 0 && payable === 0
  return (
    <DashCard
      title="How much is owed to my clients, and by them?"
      hint="Unpaid invoices and bills, added up across clients."
      state={missing || none ? 'empty' : state}
      empty={missing ? 'Not shown for your role, or for firms with very many clients. Open a client to see its figures.' : 'No unpaid invoices or bills have been posted yet.'}
      skeleton="h-40"
    >
      <dl className="grid grid-cols-2 gap-4">
        <div>
          <dt className="text-xs text-muted-foreground">Customers owe your clients</dt>
          <dd className="num text-2xl font-semibold text-heading" title={formatPaise(receivable ?? 0)}>
            {formatCompact(receivable ?? 0)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Your clients owe suppliers</dt>
          <dd className="num text-2xl font-semibold text-heading" title={formatPaise(payable ?? 0)}>
            {formatCompact(payable ?? 0)}
          </dd>
        </div>
      </dl>
      {agingTotal > 0 && (
        <div className="mt-4 border-t pt-3">
          <p className="mb-1.5 text-xs text-muted-foreground">How old the money customers owe is</p>
          <ul className="grid grid-cols-2 gap-x-4 gap-y-1 text-[13px] sm:grid-cols-4">
            {aging.map((b) => (
              <li key={b.bucket} className="flex items-baseline justify-between gap-2">
                <span className={b.bucket === 'Over 90' && b.amount_paise > 0 ? 'text-destructive' : 'text-muted-foreground'}>{b.bucket === 'Over 90' ? 'Over 90 days' : `${b.bucket} days`}</span>
                <span className="num font-medium text-heading" title={formatPaise(b.amount_paise)}>
                  {formatCompact(b.amount_paise)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
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
export function AtRiskCard({ data, state, title = 'Which clients are at risk, and why?' }: CardProps & { title?: string }) {
  const rows = useMemo(
    () =>
      (data?.clients ?? [])
        .map((c) => ({ c, h: clientHealth(c) }))
        .filter((r) => r.h.health !== 'on_track')
        .sort((a, b) => Number(b.h.health === 'overdue') - Number(a.h.health === 'overdue') || b.h.reasons.length - a.h.reasons.length || a.c.name.localeCompare(b.c.name))
        .slice(0, 8),
    [data],
  )
  return (
    <DashCard title={title} hint="Late: a date has passed. At risk: a check is failing." state={state === 'ready' && rows.length === 0 ? 'empty' : state} empty="No client is at risk." to="/alerts" seeAll="See alerts" skeleton="h-48">
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
export function ActionCard({ data, state, title, hint, empty, limit = 8, pick }: CardProps & { title: string; hint: string; empty: string; limit?: number; pick?: (c: PortfolioClient) => boolean }) {
  const all = useMemo(() => actionsFor((data?.clients ?? []).filter(pick ?? (() => true))), [data, pick])
  return (
    <DashCard title={title} hint={hint} state={state === 'ready' && all.length === 0 ? 'empty' : state} empty={empty} skeleton="h-56">
      <ActionList items={all.slice(0, limit)} more={all.length - limit} moreTo="/pipeline" />
    </DashCard>
  )
}
