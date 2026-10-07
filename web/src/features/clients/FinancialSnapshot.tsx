// A client's money for the financial year on screen, as the cards of the client page: money in and out,
// profit, tax to pay, the month-by-month chart, who owes whom, where the money sits, and the biggest costs.
// All of it is read from the journal by the server, so it can never disagree with a report. The page
// (ClientOverview) places the cards; each one handles its own loading and failure.

import type { UseQueryResult } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import type { ClientSnapshot } from '@/api/types'
import { DashCard, type CardState } from '@/components/ca/DashCard'
import { ErrorState } from '@/components/ca/Page'
import { KpiCard } from '@/components/ca/KpiCard'
import { MonthBars } from '@/components/charts/MonthBars'
import { RankedBars } from '@/components/charts/RankedBars'
import { isApiError } from '@/api/errors'
import { formatCompact, formatDate, formatPaise } from '@/lib/format'
import { pct } from '@/lib/pct'

type Q = UseQueryResult<ClientSnapshot>

/** What the whole of last year came to, shown beside this year only when last year has figures. This year is usually part-way through, so it says "in full" and never a percentage. */
function withLastYear(note: ReactNode, prior: number | null | undefined): ReactNode {
  if (prior === null || prior === undefined) return note
  return (
    <>
      <span className="block">{note}</span>
      <span className="mt-0.5 block text-muted-foreground">Last year in full: {formatCompact(prior)}</span>
    </>
  )
}

const stateOf = (q: Q): CardState => (q.isLoading || (!q.data && !q.error) ? 'loading' : q.error ? 'error' : 'ready')
const REPORTS = '/clients/$clientId/reports'

/** Whether the year has any posted money at all. */
export const hasPosted = (s: ClientSnapshot) => s.trend.some((m) => m.income_paise !== 0 || m.expense_paise !== 0) || s.income_paise !== 0 || s.expense_paise !== 0

/** The four figures: money in, money out, profit or loss, tax still to pay. */
export function MoneyKpis({ query, clientId }: { query: Q; clientId: string }) {
  const s = query.data
  if (query.error) return isApiError(query.error) && query.error.status === 403 ? null : <div className="col-span-full"><ErrorState error={query.error} retry={() => void query.refetch()} /></div>
  const loading = stateOf(query) === 'loading'
  const posted = s ? hasPosted(s) : false
  const tds = Math.max(s?.tds_payable_paise ?? 0, 0)
  const gst = Math.max(s?.gst_net_payable_paise ?? 0, 0)
  const tax = tds + gst
  const params = { clientId }
  const none = <span className="text-faint">—</span>
  return (
    <>
      <KpiCard
        loading={loading}
        label="Money in this year"
        value={s && posted ? formatCompact(s.income_paise) : none}
        valueTitle={s ? formatPaise(s.income_paise) : undefined}
        note={withLastYear(posted ? 'Sales and other income, from entries in the books' : 'Nothing has been recorded yet', s?.prior_income_paise)}
        to={REPORTS}
        params={params}
        search={{ report: 'pl' }}
      />
      <KpiCard
        loading={loading}
        label="Money out this year"
        value={s && posted ? formatCompact(s.expense_paise) : none}
        valueTitle={s ? formatPaise(s.expense_paise) : undefined}
        note={withLastYear(posted ? 'Costs and expenses' : 'Nothing has been recorded yet', s?.prior_expense_paise)}
        to={REPORTS}
        params={params}
        search={{ report: 'pl' }}
      />
      <KpiCard
        loading={loading}
        label={s && s.profit_paise < 0 ? 'Loss this year' : 'Profit this year'}
        value={s && posted ? formatCompact(Math.abs(s.profit_paise)) : none}
        valueTitle={s ? formatPaise(s.profit_paise) : undefined}
        note={posted ? 'Money in less money out' : 'Nothing has been recorded yet'}
        tone={s && s.profit_paise < 0 ? 'attention' : 'plain'}
        to={REPORTS}
        params={params}
        search={{ report: 'pl' }}
      />
      <KpiCard
        loading={loading}
        label="Tax still to pay"
        value={tax > 0 ? formatCompact(tax) : none}
        valueTitle={formatPaise(tax)}
        note={tax > 0 ? [tds > 0 && `TDS ${formatCompact(tds)}`, gst > 0 && `GST ${formatCompact(gst)}`].filter(Boolean).join(' · ') : 'No tax is pending'}
        tone={tax > 0 ? 'attention' : 'plain'}
        to="/clients/$clientId/tds"
        params={params}
      />
    </>
  )
}

/** D6: money in against money out, by month. */
export function MonthlyCard({ query, clientId }: { query: Q; clientId: string }) {
  const s = query.data
  const state = stateOf(query)
  return (
    <DashCard
      title="How has money moved month by month?"
      hint="Money in against money out, April to March."
      state={state === 'ready' && s && !hasPosted(s) ? 'empty' : state}
      empty="Nothing has been posted in this year yet."
      error={query.error}
      onRetry={() => void query.refetch()}
      to="/clients/$clientId/daybook"
      params={{ clientId }}
      seeAll="Open the entries"
      skeleton="h-72"
    >
      {s && <MonthBars trend={s.trend} />}
    </DashCard>
  )
}

function Party({ rows }: { rows: ClientSnapshot['owed']['receivables']['top'] }) {
  return (
    <ul className="mt-2 divide-y border-t">
      {rows.slice(0, 3).map((p) => (
        <li key={p.name} className="flex items-baseline justify-between gap-3 py-1.5 text-sm">
          <span className="min-w-0 truncate text-muted-foreground" title={p.name}>
            {p.name}
          </span>
          <span className="num shrink-0 text-heading">{p.amount_display}</span>
        </li>
      ))}
    </ul>
  )
}

function Side({ title, side, report, clientId, none }: { title: string; side: ClientSnapshot['owed']['receivables']; report: 'receivables' | 'payables'; clientId: string; none: string }) {
  return (
    <div className="min-w-0">
      <h3 className="text-xs text-muted-foreground">{title}</h3>
      <p className="num text-xl font-semibold text-heading" title={formatPaise(side.total_paise)}>
        {side.total_paise > 0 ? formatCompact(side.total_paise) : '—'}
      </p>
      {side.over_90_paise > 0 ? (
        <p className="text-xs font-medium text-destructive">{formatCompact(side.over_90_paise)} is over 90 days old</p>
      ) : (
        <p className="text-xs text-muted-foreground">{side.total_paise > 0 ? 'Nothing over 90 days old' : none}</p>
      )}
      {side.top.length > 0 && <Party rows={side.top} />}
      {side.total_paise > 0 && (
        <Link to={REPORTS} params={{ clientId }} search={{ report } as never} className="mt-1 inline-flex min-h-8 items-center text-xs text-link underline underline-offset-2 max-sm:min-h-11">
          See the full list
        </Link>
      )}
    </div>
  )
}

/** D8: what customers owe, and what is owed to suppliers. */
export function OwedCard({ query, clientId }: { query: Q; clientId: string }) {
  const s = query.data
  const state = stateOf(query)
  const nothing = !!s && s.owed.receivables.total_paise === 0 && s.owed.payables.total_paise === 0
  return (
    <DashCard
      title="Who owes me, and whom do I owe?"
      hint="Unpaid sales and unpaid bills, the biggest three of each."
      state={state === 'ready' && nothing ? 'empty' : state}
      empty="No unpaid bills or invoices."
      error={query.error}
      onRetry={() => void query.refetch()}
      skeleton="h-56"
    >
      {s && (
        <div className="@container">
         <div className="grid gap-5 @md:grid-cols-2">
          <Side title="Customers owe me" side={s.owed.receivables} report="receivables" clientId={clientId} none="No unpaid sales" />
          <Side title="I owe suppliers" side={s.owed.payables} report="payables" clientId={clientId} none="No unpaid bills" />
         </div>
        </div>
      )}
    </DashCard>
  )
}

/** D9: bank, card and loan balances. */
export function AccountsCard({ query, clientId }: { query: Q; clientId: string }) {
  const s = query.data
  const state = stateOf(query)
  return (
    <DashCard
      title="Where is my money?"
      hint="Bank balances, and what is owed on cards and loans."
      state={state === 'ready' && s?.accounts.length === 0 ? 'empty' : state}
      empty="No bank account has been added yet."
      error={query.error}
      onRetry={() => void query.refetch()}
      to="/clients/$clientId/statements"
      params={{ clientId }}
      seeAll="See statements"
      skeleton="h-40"
    >
      <ul className="divide-y">
        {s?.accounts.map((a) => (
          <li key={a.label} className="flex items-baseline justify-between gap-3 py-2 text-sm first:pt-0 last:pb-0">
            <span className="min-w-0 truncate text-muted-foreground" title={a.label}>
              {a.label}
            </span>
            <span className="num shrink-0 font-medium text-heading">
              {a.balance_display}
              {a.kind === 'CARD' || a.kind === 'LOAN' ? <span className="ml-1 text-xs font-normal text-muted-foreground">owed</span> : null}
            </span>
          </li>
        ))}
      </ul>
    </DashCard>
  )
}

/** D10: the five biggest expense heads. */
export function CostsCard({ query, clientId }: { query: Q; clientId: string }) {
  const s = query.data
  const state = stateOf(query)
  return (
    <DashCard
      title="What do I spend the most on?"
      hint="The biggest costs this year, and their share of all money out."
      state={state === 'ready' && s?.top_expenses.length === 0 ? 'empty' : state}
      empty="No expenses have been recorded yet."
      error={query.error}
      onRetry={() => void query.refetch()}
      to={REPORTS}
      params={{ clientId }}
      search={{ report: 'pl' }}
      seeAll="Profit and loss"
      skeleton="h-40"
    >
      <RankedBars
        rows={(s?.top_expenses ?? []).slice(0, 5).map((r) => ({
          key: r.ledger,
          label: r.ledger,
          value: r.amount_paise,
          valueLabel: r.amount_display ?? formatCompact(r.amount_paise),
          note: s ? `${pct(r.amount_paise, s.expense_paise)}% of all money out` : undefined,
          tone: 'accent' as const,
        }))}
      />
    </DashCard>
  )
}

/** The line under the cards: GST position and the date the figures are as at. */
export function SnapshotFootnote({ query }: { query: Q }) {
  const s = query.data
  if (!s) return null
  return (
    <p className="text-xs text-muted-foreground">
      GST in the books: {s.gst_net_payable_paise >= 0 ? `${formatPaise(s.gst_net_payable_paise)} to pay` : `${formatPaise(-s.gst_net_payable_paise)} of credit carried forward`}. Figures are as at {formatDate(s.as_of)}.
    </p>
  )
}

const TILES: { report: string; ready: string; title: string; note: string }[] = [
  { report: 'pl', ready: 'pnl', title: 'Profit and loss', note: 'Did the business make money?' },
  { report: 'bs', ready: 'balance_sheet', title: 'Balance sheet', note: 'What it owns and what it owes' },
  { report: 'tb', ready: 'trial_balance', title: 'Trial balance', note: 'The balance of every account' },
  { report: 'receivables', ready: 'receivables', title: 'Who owes me', note: 'Unpaid sales, by customer' },
  { report: 'payables', ready: 'payables', title: 'Whom I owe', note: 'Unpaid bills, by supplier' },
]

/** "Ready" or "Not ready yet: <why>", in words, from the server's `reports_ready`. A report that is not ready still opens. */
function Readiness({ ready }: { ready: ClientSnapshot['reports_ready'][number] | undefined }) {
  if (!ready) return null
  return ready.ready ? (
    <span className="text-xs font-medium text-success">Ready</span>
  ) : (
    <span className="text-xs text-accent-foreground">Not ready yet{ready.reason ? `: ${ready.reason}` : ''}</span>
  )
}

/** D11: the reports a client can open, each saying whether it is ready to rely on. */
export function ReportTiles({ clientId, gst, query }: { clientId: string; gst: boolean; query?: Q }): ReactNode {
  const box = 'grid min-h-[4.5rem] content-center gap-0.5 rounded-lg border bg-card px-4 py-3 hover:bg-hover'
  const byKey = new Map((query?.data?.reports_ready ?? []).map((r) => [r.key, r]))
  return (
    <DashCard title="Which reports can I open?" hint="Each one opens on the year you are looking at." skeleton="h-24">
      <ul className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
        {TILES.map((t) => (
          <li key={t.report}>
            <Link to={REPORTS} params={{ clientId }} search={{ report: t.report } as never} className={box}>
              <span className="text-sm font-semibold text-heading">{t.title}</span>
              <span className="text-xs text-muted-foreground">{t.note}</span>
              <Readiness ready={byKey.get(t.ready as never)} />
            </Link>
          </li>
        ))}
        <li>
          <Link to="/clients/$clientId/tds" params={{ clientId }} className={box}>
            <span className="text-sm font-semibold text-heading">TDS</span>
            <span className="text-xs text-muted-foreground">Tax deducted and deposited</span>
            <Readiness ready={byKey.get('tds' as never)} />
          </Link>
        </li>
        {gst && (
          <li>
            <Link to="/clients/$clientId/gst" params={{ clientId }} className={box}>
              <span className="text-sm font-semibold text-heading">GST</span>
              <span className="text-xs text-muted-foreground">Returns and what is payable</span>
              <Readiness ready={byKey.get('gst' as never)} />
            </Link>
          </li>
        )}
      </ul>
    </DashCard>
  )
}
