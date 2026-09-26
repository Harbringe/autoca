// Trial Balance, Profit & Loss A/c, Balance Sheet, and the bank reconciliation, for the year
// chosen at the top.
//
// Laid out as they are printed in practice: the P&L and Balance Sheet horizontally, expenses
// or liabilities on the left, the profit carried across. Anything that is not final says so
// -- a report with rows still waiting is Provisional -- and a Trial Balance that does not
// tally says by how much. Every one prints on a plain page with the client, year and date.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { AlertTriangle, CheckCircle2, Printer } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { balanceSheet, profitAndLoss, reconciliation, trialBalance } from '@/api/queries/books'
import { bankAccounts, statements } from '@/api/queries/clients'
import type { LedgerBalance, ReportFooter } from '@/api/types'
import { GROUP_LABEL } from '@/api/types'
import { Money } from '@/components/ca/Money'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select, tbl } from '@/components/ui/controls'
import { DateInput } from '@/components/ui/date-input'
import { Spinner } from '@/components/ui/spinner'
import { asAt, formatDate, formatDateTime, formatPaise, fyLabel, parseDate } from '@/lib/format'
import { usePreferences } from '@/lib/preferences'
import { cn } from '@/lib/utils'

export type ReportTab = 'tb' | 'pl' | 'bs' | 'recon'

const TABS: { tab: ReportTab; label: string }[] = [
  { tab: 'tb', label: 'Trial Balance' },
  { tab: 'pl', label: 'Profit & Loss A/c' },
  { tab: 'bs', label: 'Balance Sheet' },
  { tab: 'recon', label: 'Bank Reconciliation' },
]

export function ReportsScreen({ clientId, report }: { clientId: string; report: ReportTab }) {
  const { fy } = usePreferences()
  return (
    <div className="grid gap-4">
      <div className="no-print flex flex-wrap items-center justify-between gap-3">
        <nav aria-label="Report" className="flex flex-wrap gap-1 rounded-lg bg-muted p-1">
          {TABS.map((t) => (
            <Link
              key={t.tab}
              to="/clients/$clientId/reports"
              params={{ clientId }}
              search={{ report: t.tab }}
              className={cn('rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground', report === t.tab && 'bg-card text-foreground shadow-xs')}
            >
              {t.label}
            </Link>
          ))}
        </nav>
        {report !== 'recon' && (
          <Button variant="outline" onClick={() => window.print()}>
            <Printer /> Print
          </Button>
        )}
      </div>
      {report === 'tb' && <TrialBalanceReport clientId={clientId} fy={fy} />}
      {report === 'pl' && <ProfitAndLossReport clientId={clientId} fy={fy} />}
      {report === 'bs' && <BalanceSheetReport clientId={clientId} fy={fy} />}
      {report === 'recon' && <Reconciliation clientId={clientId} />}
    </div>
  )
}

/** The heading every printed report carries, and the warning when the figures are not final. */
function ReportFrame({ title, footer, children, period }: { title: string; footer: ReportFooter; children: ReactNode; period?: string }) {
  return (
    <Card className="p-5 print:border-0 print:p-0 print:shadow-none">
      <div className="mb-4 text-center">
        <div className="text-lg font-semibold">{footer.client_name}</div>
        <div className="font-medium">{title}</div>
        <div className="text-sm text-muted-foreground">
          {period ?? `for the year ${formatDate(footer.period_start)} to ${formatDate(footer.period_end)} (FY ${footer.fy_label})`}
        </div>
      </div>
      {!footer.is_complete && (
        <div className="mb-4 flex gap-2 rounded-md border border-warning/50 bg-warning/10 p-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <span>
            <strong>Provisional.</strong> {footer.pending_review} transaction{footer.pending_review === 1 ? '' : 's'} in this period{' '}
            {footer.pending_review === 1 ? 'is' : 'are'} not yet posted, so these figures will change.
          </span>
        </div>
      )}
      {children}
      <div className="mt-4 flex justify-between gap-4 border-t pt-2 text-xs text-muted-foreground">
        <span>{footer.caption || `${footer.entry_count} entries`}</span>
        <span>Generated {formatDateTime(footer.generated_at)}</span>
      </div>
    </Card>
  )
}

function reportState<T>(q: { data?: T; isPending: boolean; error: unknown; refetch: () => unknown }) {
  if (q.isPending) return { node: <Spinner label="Preparing the report…" /> }
  if (q.error) return { node: <ErrorState error={q.error} retry={() => void q.refetch()} /> }
  return { data: q.data as T }
}

function TrialBalanceReport({ clientId, fy }: { clientId: string; fy: number }) {
  const r = reportState(useQuery(trialBalance(clientId, fy)))
  if (!r.data) return r.node
  const tb = r.data
  if (tb.rows.length === 0) return <NothingYet clientId={clientId} fy={fy} />
  const diff = tb.total_debit_paise - tb.total_credit_paise
  return (
    <ReportFrame title="Trial Balance" footer={tb.footer} period={asAt(fy)}>
      {!tb.balances && (
        <div className="mb-4 flex gap-2 rounded-md border border-destructive/50 bg-destructive/8 p-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
          <span>
            <strong>The Trial Balance does not tally.</strong> Debits exceed credits by {formatPaise(diff)}.
          </span>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className={tbl.table}>
          <thead className={tbl.head}>
            <tr>
              <th className={tbl.th}>Particulars</th>
              <th className={tbl.th}>Group</th>
              <th className={tbl.thNum}>Opening</th>
              <th className={tbl.thNum}>Debit</th>
              <th className={tbl.thNum}>Credit</th>
              <th className={tbl.thNum}>Closing Dr</th>
              <th className={tbl.thNum}>Closing Cr</th>
            </tr>
          </thead>
          <tbody>
            {tb.rows.map((row) => (
              <tr key={row.name} className={tbl.row}>
                <td className={tbl.td}>{row.name}</td>
                <td className={`${tbl.td} text-muted-foreground`}>{GROUP_LABEL[row.group ?? ''] ?? row.group}</td>
                <td className={tbl.tdNum}><Money muted display={drCr(row.opening_paise)} /></td>
                <td className={tbl.tdNum}><Money muted display={row.debit_display} /></td>
                <td className={tbl.tdNum}><Money muted display={row.credit_display} /></td>
                <td className={tbl.tdNum}><Money muted display={row.closing_debit_paise ? row.closing_debit_display : ''} /></td>
                <td className={tbl.tdNum}><Money muted display={row.closing_credit_paise ? row.closing_credit_display : ''} /></td>
              </tr>
            ))}
          </tbody>
          <tfoot className={tbl.foot}>
            <tr>
              <td className={tbl.td} colSpan={5}>
                Grand Total
                {tb.balances && <CheckCircle2 className="ml-2 inline size-4 text-success" aria-label="Tallies" />}
              </td>
              <td className={tbl.tdNum}>{tb.total_debit_display}</td>
              <td className={tbl.tdNum}>{tb.total_credit_display}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </ReportFrame>
  )
}

/** An opening balance written with its side, as ledgers show it. Debits are positive. */
function drCr(paise: number): string {
  if (!paise) return ''
  return `${formatPaise(Math.abs(paise), { sign: false })} ${paise > 0 ? 'Dr' : 'Cr'}`
}

/** A side of a horizontal statement: its lines, padded so both sides end on the same row. */
function Side({ heading, rows, total, rowsTo, amount }: { heading: string; rows: [string, string | null][]; total: string | null; rowsTo: number; amount: string }) {
  const padded = [...rows, ...Array.from({ length: Math.max(0, rowsTo - rows.length) }, () => ['', null] as [string, string | null])]
  return (
    <table className={cn(tbl.table, 'h-full')}>
      <thead className={tbl.head}>
        <tr>
          <th className={tbl.th}>{heading}</th>
          <th className={tbl.thNum}>{amount}</th>
        </tr>
      </thead>
      <tbody>
        {padded.map(([name, value], i) => (
          <tr key={`${name}-${i}`} className="h-(--row-h) border-b border-dashed last:border-b-0">
            <td className={tbl.td}>{name}</td>
            <td className={tbl.tdNum}>{value && <Money display={value} />}</td>
          </tr>
        ))}
      </tbody>
      <tfoot className={tbl.foot}>
        <tr>
          <td className={tbl.td}>Total</td>
          <td className={tbl.tdNum}>{total}</td>
        </tr>
      </tfoot>
    </table>
  )
}

const closing = (r: LedgerBalance, side: 'dr' | 'cr') =>
  side === 'dr' ? (r.closing_debit_paise ? r.closing_debit_display : r.closing_credit_paise ? `(-) ${r.closing_credit_display}` : null) : r.closing_credit_paise ? r.closing_credit_display : r.closing_debit_paise ? `(-) ${r.closing_debit_display}` : null

function ProfitAndLossReport({ clientId, fy }: { clientId: string; fy: number }) {
  const r = reportState(useQuery(profitAndLoss(clientId, fy)))
  if (!r.data) return r.node
  const pl = r.data
  if (!pl.income.length && !pl.expenses.length) return <NothingYet clientId={clientId} fy={fy} />
  const profit = pl.net_profit_paise >= 0
  const net = formatPaise(Math.abs(pl.net_profit_paise))
  const left: [string, string | null][] = pl.expenses.map((e) => [e.name, closing(e, 'dr')])
  const right: [string, string | null][] = pl.income.map((i) => [i.name, closing(i, 'cr')])
  if (profit) left.push(['Net Profit (carried to Capital)', net])
  else right.push(['Net Loss (carried to Capital)', net])
  const total = formatPaise(Math.max(pl.total_income_paise, pl.total_expenses_paise))
  const rowsTo = Math.max(left.length, right.length)
  return (
    <ReportFrame title="Profit & Loss A/c" footer={pl.footer}>
      <div className="grid gap-4 md:grid-cols-2 md:gap-0 md:divide-x">
        <Side heading="Dr · Expenses" amount="Amount" rows={left} rowsTo={rowsTo} total={total} />
        <Side heading="Cr · Income" amount="Amount" rows={right} rowsTo={rowsTo} total={total} />
      </div>
      <p className={cn('mt-3 text-sm font-medium', profit ? 'text-success' : 'text-destructive')}>
        {profit ? 'Net Profit' : 'Net Loss'} for the year: {net}
      </p>
    </ReportFrame>
  )
}

function BalanceSheetReport({ clientId, fy }: { clientId: string; fy: number }) {
  const r = reportState(useQuery(balanceSheet(clientId, fy)))
  if (!r.data) return r.node
  const bs = r.data
  if (!bs.assets.length && !bs.liabilities.length) return <NothingYet clientId={clientId} fy={fy} />
  const liabilities: [string, string | null][] = bs.liabilities.map((l) => [l.name, closing(l, 'cr')])
  liabilities.push([bs.net_profit_paise >= 0 ? 'Add: Net Profit for the year' : 'Less: Net Loss for the year', formatPaise(Math.abs(bs.net_profit_paise))])
  const assets: [string, string | null][] = bs.assets.map((a) => [a.name, closing(a, 'dr')])
  const rowsTo = Math.max(liabilities.length, assets.length)
  return (
    <ReportFrame title="Balance Sheet" footer={bs.footer} period={asAt(fy)}>
      {!bs.balances && (
        <div className="mb-4 flex gap-2 rounded-md border border-destructive/50 bg-destructive/8 p-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
          <span>
            <strong>The Balance Sheet does not balance.</strong> Liabilities and profit are {bs.total_liabilities_and_profit_display}; assets
            are {bs.total_assets_display}.
          </span>
        </div>
      )}
      {bs.suspense_paise !== 0 && (
        <div className="mb-4 rounded-md border border-warning/50 bg-warning/10 p-3 text-sm">
          <strong>{bs.suspense_display}</strong> is in Suspense A/c. Place those transactions in their proper ledgers before finalising.
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-2 md:gap-0 md:divide-x">
        <Side heading="Liabilities" amount="Amount" rows={liabilities} rowsTo={rowsTo} total={bs.total_liabilities_and_profit_display} />
        <Side heading="Assets" amount="Amount" rows={assets} rowsTo={rowsTo} total={bs.total_assets_display} />
      </div>
    </ReportFrame>
  )
}

function NothingYet({ clientId, fy }: { clientId: string; fy: number }) {
  return (
    <EmptyState title={`No entries in FY ${fyLabel(fy)}`}>
      Reports are built from posted entries. Post transactions from{' '}
      <Link to="/clients/$clientId/review" params={{ clientId }} search={{ stage: 'unresolved' }} className="underline">
        Review
      </Link>
      , or choose another financial year at the top.
    </EmptyState>
  )
}

function Reconciliation({ clientId }: { clientId: string }) {
  const accounts = useQuery(bankAccounts(clientId))
  const stmts = useQuery(statements(clientId))
  const [accountId, setAccountId] = useState('')
  const [asOfText, setAsOfText] = useState('')

  const list = accounts.data?.results ?? []
  const account = list.find((a) => a.id === accountId) ?? list[0]
  const latest = (stmts.data?.results ?? [])
    .filter((s) => s.bank_account === account?.id)
    .reduce<string | null>((max, s) => (!max || s.period_end > max ? s.period_end : max), null)
  useEffect(() => {
    if (latest && !asOfText) setAsOfText(formatDate(latest))
  }, [latest, asOfText])
  const asOf = parseDate(asOfText)
  const check = useQuery({ ...reconciliation(clientId, account?.id ?? '', asOf ?? ''), enabled: !!account && !!asOf })

  if (accounts.isPending) return <Spinner />
  if (!list.length) return <EmptyState title="No bank accounts yet">Upload a statement first.</EmptyState>

  return (
    <Card className="grid max-w-2xl gap-4 p-5">
      <div>
        <div className="font-medium">Does the bank ledger agree with the bank?</div>
        <p className="text-sm text-muted-foreground">The balance in the books on a date, against the balance the bank’s statement shows on it.</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="grid gap-1.5">
          <label className="text-[13px] font-medium" htmlFor="recon-account">Bank account</label>
          <Select id="recon-account" value={account?.id} onChange={(e) => { setAccountId(e.target.value); setAsOfText('') }}>
            {list.map((a) => (
              <option key={a.id} value={a.id}>{a.label}</option>
            ))}
          </Select>
        </div>
        <div className="grid gap-1.5">
          <label className="text-[13px] font-medium" htmlFor="recon-date">As at</label>
          <DateInput id="recon-date" value={asOfText} onChange={(e) => setAsOfText(e.target.value)} />
        </div>
      </div>
      {!asOf ? (
        <p className="text-sm text-muted-foreground">Enter a date as DD-MM-YYYY.</p>
      ) : check.isPending ? (
        <Spinner />
      ) : check.error ? (
        <ErrorState error={check.error} />
      ) : (
        <div className="grid gap-3">
          <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1.5 text-sm">
            <dt>Balance as per books</dt>
            <dd className="num text-right font-medium">{check.data.ledger_balance_display}</dd>
            <dt>Balance as per bank statement</dt>
            <dd className="num text-right font-medium">{check.data.statement_balance_display}</dd>
            <dt className="border-t pt-1.5 font-medium">Difference</dt>
            <dd className={cn('num border-t pt-1.5 text-right font-semibold', check.data.matches ? 'text-success' : 'text-destructive')}>
              {check.data.difference_display}
            </dd>
          </dl>
          <div
            className={cn(
              'flex gap-2 rounded-md p-3 text-sm',
              check.data.matches ? 'border border-success/40 bg-success/8' : 'border border-warning/50 bg-warning/10',
            )}
          >
            {check.data.matches ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" /> : <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />}
            <span>{check.data.explanation}</span>
          </div>
          {check.data.unapproved_count > 0 && (
            <p className="text-sm text-muted-foreground">
              {check.data.unapproved_count} transaction{check.data.unapproved_count === 1 ? '' : 's'} up to this date {check.data.unapproved_count === 1 ? 'is' : 'are'} not posted.{' '}
              <Link to="/clients/$clientId/review" params={{ clientId }} search={{ stage: 'all' }} className="underline">
                Post them in Review
              </Link>
              .
            </p>
          )}
        </div>
      )}
    </Card>
  )
}
