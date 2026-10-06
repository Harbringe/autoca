// A client's position and trend for the financial year on screen: profit, income against expense by month,
// the biggest expense heads, bank / card / loan balances, who owes whom, and the GST and TDS balances.
// All of it is read from the journal by the server, so it can never disagree with a report.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { clientSnapshot } from '@/api/queries/dashboard'
import type { ClientSnapshot } from '@/api/types'
import { ErrorState } from '@/components/ca/Page'
import { Card } from '@/components/ui/card'
import { StatCard, StatGrid } from '@/components/ui/stat-card'
import { formatCompact, formatDate, formatPaise } from '@/lib/format'
import { cn } from '@/lib/utils'

const MONTHS = ['Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar']

export function FinancialSnapshot({ clientId, fy }: { clientId: string; fy: number }) {
  const query = useQuery(clientSnapshot(clientId, fy))
  if (query.error) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  if (query.isLoading || !query.data) return <div className="skeleton h-40 rounded-lg" aria-busy="true" aria-label="Loading the financial position" />
  const s = query.data
  const empty = s.trend.every((m) => m.income_paise === 0 && m.expense_paise === 0)

  return (
    <section aria-labelledby="fin-title" className="grid gap-4">
      <h2 id="fin-title" className="sr-only">Financial position</h2>
      <StatGrid>
        <StatCard label="Income" value={formatCompact(s.income_paise)} valueTitle={formatPaise(s.income_paise)} note="This financial year, from posted entries" />
        <StatCard label="Expense" value={formatCompact(s.expense_paise)} valueTitle={formatPaise(s.expense_paise)} note="Direct and indirect" />
        <StatCard label={s.profit_paise < 0 ? 'Loss' : 'Profit'} value={formatCompact(Math.abs(s.profit_paise))} valueTitle={formatPaise(s.profit_paise)} note="Income less expense" tone={s.profit_paise < 0 ? 'attention' : 'plain'} />
        <StatCard label="TDS to deposit" value={s.tds_payable_paise > 0 ? formatCompact(s.tds_payable_paise) : '—'} valueTitle={formatPaise(s.tds_payable_paise)} note="Deducted, not yet deposited" to={`/clients/${clientId}/tds`} />
      </StatGrid>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <Card className="p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-[15px] font-semibold text-heading">Income and expense by month</h3>
            <span className="flex items-center gap-3 text-xs text-muted-foreground"><Key className="bg-success" label="Income" /><Key className="bg-accent-foreground" label="Expense" /></span>
          </div>
          {empty ? <p className="mt-3 text-sm text-muted-foreground">Nothing has been posted in this financial year yet.</p> : <MonthBars trend={s.trend} />}
        </Card>

        <Card className="p-5">
          <h3 className="text-[15px] font-semibold text-heading">Biggest expenses</h3>
          {s.top_expenses.length === 0 ? <p className="mt-3 text-sm text-muted-foreground">No expenses posted yet.</p> : <TopExpenses rows={s.top_expenses} />}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="p-5 text-sm">
          <h3 className="mb-2 text-[15px] font-semibold text-heading">Bank, card and loan balances</h3>
          {s.accounts.length === 0 ? <p className="text-muted-foreground">No account yet.</p> : (
            <ul className="divide-y">
              {s.accounts.map((a) => (
                <li key={a.label} className="flex items-baseline justify-between gap-3 py-2">
                  <span className="min-w-0 truncate text-muted-foreground" title={a.label}>{a.label}</span>
                  <span className="num shrink-0 font-medium text-heading">{a.balance_display}{a.kind === 'CARD' || a.kind === 'LOAN' ? <span className="ml-1 text-xs font-normal text-muted-foreground">owed</span> : null}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <OwedCard title="Customers owe" side={s.owed.receivables} to={`/clients/${clientId}/reports`} />
        <OwedCard title="Owed to suppliers" side={s.owed.payables} to={`/clients/${clientId}/reports`} />
      </div>

      <p className="text-xs text-muted-foreground">
        GST in the books: {s.gst_net_payable_paise >= 0 ? `${formatPaise(s.gst_net_payable_paise)} payable` : `${formatPaise(-s.gst_net_payable_paise)} input credit carried`}. Figures are as at {formatDate(s.as_of)}.
      </p>
    </section>
  )
}

function Key({ className, label }: { className: string; label: string }) {
  return <span className="flex items-center gap-1.5"><span className={cn('size-2.5 rounded-sm', className)} aria-hidden />{label}</span>
}

/** Paired bars for each month, drawn in SVG so they scale to the card and need no chart library. */
function MonthBars({ trend }: { trend: ClientSnapshot['trend'] }) {
  const top = Math.max(...trend.flatMap((m) => [m.income_paise, m.expense_paise]), 1)
  const width = 480
  const height = 150
  const slot = width / trend.length
  const bar = slot * 0.34
  const scale = (paise: number) => Math.max((Math.max(paise, 0) / top) * height, paise > 0 ? 2 : 0)
  const summary = trend.map((m, i) => `${MONTHS[i] ?? m.month}: income ${formatPaise(m.income_paise)}, expense ${formatPaise(m.expense_paise)}`).join('; ')
  return (
    <div className="mt-3">
      <svg viewBox={`0 0 ${width} ${height + 20}`} className="h-auto w-full" role="img" aria-label={`Income and expense by month. ${summary}`}>
        <line x1="0" x2={width} y1={height} y2={height} className="stroke-border" />
        {trend.map((m, i) => {
          const x = i * slot + slot / 2
          return (
            <g key={m.month}>
              <title>{`${MONTHS[i] ?? m.month}: income ${formatPaise(m.income_paise)}, expense ${formatPaise(m.expense_paise)}`}</title>
              <rect x={x - bar - 1} y={height - scale(m.income_paise)} width={bar} height={scale(m.income_paise)} rx="1.5" className="fill-success" />
              <rect x={x + 1} y={height - scale(m.expense_paise)} width={bar} height={scale(m.expense_paise)} rx="1.5" className="fill-accent-foreground" />
              <text x={x} y={height + 14} textAnchor="middle" className="fill-muted-foreground text-[10px]">{MONTHS[i] ?? m.month}</text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

function TopExpenses({ rows }: { rows: ClientSnapshot['top_expenses'] }) {
  const top = Math.max(...rows.map((r) => r.amount_paise), 1)
  return (
    <ul className="mt-3 grid gap-3">
      {rows.map((r) => (
        <li key={r.ledger} className="grid gap-1">
          <span className="flex items-baseline justify-between gap-3 text-xs"><span className="min-w-0 truncate text-muted-foreground" title={r.ledger}>{r.ledger}</span><strong className="num text-heading">{r.amount_display}</strong></span>
          <span className="h-2 overflow-hidden rounded-full bg-muted"><span className="block h-full rounded-full bg-accent-foreground" style={{ width: `${(r.amount_paise / top) * 100}%` }} /></span>
        </li>
      ))}
    </ul>
  )
}

function OwedCard({ title, side, to }: { title: string; side: ClientSnapshot['owed']['receivables']; to: string }) {
  return (
    <Card className="p-5 text-sm">
      <h3 className="mb-1 text-[15px] font-semibold text-heading">{title}</h3>
      <p className="num text-xl font-semibold text-heading">{side.total_display}</p>
      {side.over_90_paise > 0 ? <p className="mt-0.5 text-xs text-destructive">{side.over_90_display} is over 90 days old</p> : <p className="mt-0.5 text-xs text-muted-foreground">Nothing over 90 days</p>}
      {side.top.length > 0 && (
        <ul className="mt-3 divide-y border-t">
          {side.top.map((p) => <li key={p.name} className="flex items-baseline justify-between gap-3 py-1.5"><span className="min-w-0 truncate text-muted-foreground" title={p.name}>{p.name}</span><span className="num shrink-0">{p.amount_display}</span></li>)}
        </ul>
      )}
      <Link to={to as never} className="mt-2 inline-block text-xs text-link underline underline-offset-2">Open reports</Link>
    </Card>
  )
}
