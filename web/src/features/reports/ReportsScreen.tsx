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
import { useEffect, useState } from 'react'
import type { ReportTab } from './tabs'
import { balanceSheet, profitAndLoss, reconciliation, trialBalance } from '@/api/queries/books'
import { bankAccounts, statements } from '@/api/queries/clients'
import type { LedgerBalance, ReportFooter } from '@/api/types'
import { GROUP_LABEL } from '@/api/types'
import { Money } from '@/components/ca/Money'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select, tbl } from '@/components/ui/controls'
import { DateInput } from '@/components/ui/date-input'
import { Spinner } from '@/components/ui/spinner'
import { asAt, closingLine, formatDate, formatDrCr, formatPaise, fyLabel, parseDate, sideTotal } from '@/lib/format'
import { useFy } from '@/features/shell/useFy'
import { FinancialStatements } from './FinancialStatements'
import { OutstandingReport } from './OutstandingReport'
import { isProvisional, OpeningLink, ReportFrame, useUnconfirmedOpenings } from './ReportFrame'
import { cn } from '@/lib/utils'

export type { ReportTab }

export function ReportsScreen({ clientId, report }: { clientId: string; report: ReportTab }) {
  const { fy } = useFy()
  return (
    <div className="grid gap-4">
      {report !== 'recon' && (
        <div className="no-print flex justify-end">
          <Button variant="secondary" onClick={() => window.print()}>
            <Printer /> Print
          </Button>
        </div>
      )}
      {report === 'tb' && <TrialBalanceReport clientId={clientId} fy={fy} />}
      {report === 'pl' && <ProfitAndLossReport clientId={clientId} fy={fy} />}
      {report === 'bs' && <BalanceSheetReport clientId={clientId} fy={fy} />}
      {(report === 'payables' || report === 'receivables') && <OutstandingReport clientId={clientId} side={report} />}
      {report === 'nce' && <FinancialStatements clientId={clientId} fy={fy} />}
      {report === 'recon' && <Reconciliation clientId={clientId} />}
    </div>
  )
}

const NO_SYMBOL = { symbol: false }


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
  // Whole paise, added as integers; the Grand Total row carries every column, as Tally's does.
  const sum = (pick: (row: LedgerBalance) => number) => tb.rows.reduce((total, row) => total + pick(row), 0)
  return (
    <ReportFrame clientId={clientId} title="Trial Balance" footer={tb.footer} period={asAt(fy)}>
      {!tb.balances && (
        <div className="mb-4 flex gap-2 rounded-md border border-destructive/40 bg-destructive-bg p-3 text-sm">
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
              <th scope="col" className={tbl.th}>Particulars</th>
              <th scope="col" className={tbl.th}>Group</th>
              <th scope="col" className={tbl.thNum}>Opening ₹</th>
              <th scope="col" className={tbl.thNum}>Debit ₹</th>
              <th scope="col" className={tbl.thNum}>Credit ₹</th>
              <th scope="col" className={tbl.thNum}>Closing Dr ₹</th>
              <th scope="col" className={tbl.thNum}>Closing Cr ₹</th>
            </tr>
          </thead>
          <tbody>
            {tb.rows.map((row) => {
              const nil = !row.closing_debit_paise && !row.closing_credit_paise
              return (
                <tr key={row.name} className={tbl.row}>
                  <td className={tbl.td}>
                    <LedgerLink clientId={clientId} ledger={row.ledger} name={row.name} />
                  </td>
                  <td className={`${tbl.td} text-muted-foreground`}>{GROUP_LABEL[row.group ?? ''] ?? row.group}</td>
                  <td className={tbl.tdNum}>
                    <Money dash display={row.opening_paise ? drCr(row.opening_paise) : undefined} paise={row.opening_paise ? undefined : 0} symbol={false} />
                  </td>
                  <td className={tbl.tdNum}><Money dash paise={row.debit_paise} symbol={false} /></td>
                  <td className={tbl.tdNum}><Money dash paise={row.credit_paise} symbol={false} /></td>
                  {/* A ledger with no balance at all stays 0.00, as auditors expect; otherwise an empty side is a dash. */}
                  <td className={tbl.tdNum}><Money dash={!nil} muted paise={row.closing_debit_paise} symbol={false} /></td>
                  <td className={tbl.tdNum}><Money dash paise={row.closing_credit_paise} symbol={false} /></td>
                </tr>
              )
            })}
          </tbody>
          <tfoot className={tbl.foot}>
            <tr>
              <td className={tbl.td} colSpan={2}>
                Grand Total
                <TallyMark clientId={clientId} footer={tb.footer} balances={tb.balances} />
              </td>
              <td className={tbl.tdNum}>{drCr(sum((row) => row.opening_paise)) || formatPaise(0, { symbol: false })}</td>
              <td className={tbl.tdNum}>{formatPaise(sum((row) => row.debit_paise), { symbol: false })}</td>
              <td className={tbl.tdNum}>{formatPaise(sum((row) => row.credit_paise), { symbol: false })}</td>
              <td className={tbl.tdNum}>{formatPaise(tb.total_debit_paise, { symbol: false })}</td>
              <td className={tbl.tdNum}>{formatPaise(tb.total_credit_paise, { symbol: false })}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </ReportFrame>
  )
}

/** A line of a report as a link to its ledger, with every voucher in it. The opening difference has no ledger: it opens the openings. */
function LedgerLink({ clientId, ledger, name }: { clientId: string; ledger?: string | null; name: string }) {
  if (ledger) {
    return (
      <Link to="/clients/$clientId/ledgers" params={{ clientId }} search={{ ledger }} className="hover:underline" title={`Open ${name}`}>
        {name}
      </Link>
    )
  }
  if (name === 'Difference in opening balances') {
    return (
      <Link to="/clients/$clientId/statements" params={{ clientId }} className="hover:underline" title="Confirm the opening balances">
        {name}
      </Link>
    )
  }
  return <>{name}</>
}

/** The green tick means "tallies and final". While the banner is up the figures are not final, so it says so instead. */
function TallyMark({ clientId, footer, balances }: { clientId: string; footer: ReportFooter; balances: boolean }) {
  const unconfirmed = useUnconfirmedOpenings(clientId)
  if (isProvisional(footer, unconfirmed)) return <Badge tone="attention" className="ml-2">Provisional</Badge>
  return balances ? <CheckCircle2 className="ml-2 inline size-4 text-success" aria-label="Tallies" /> : null
}

/** An opening balance written with its side, as ledgers show it. Debits are positive. */
function drCr(paise: number): string {
  if (!paise) return ''
  return `${formatPaise(Math.abs(paise), { sign: false, symbol: false })} ${paise > 0 ? 'Dr' : 'Cr'}`
}

/** A side of a horizontal statement: its lines, padded so both sides end on the same row. */
type SideRow = [name: string, value: string | null, ledger?: string | null]

function Side({ clientId, heading, rows, total, rowsTo, amount }: { clientId: string; heading: string; rows: SideRow[]; total: string | null; rowsTo: number; amount: string }) {
  const padded: SideRow[] = [...rows, ...Array.from({ length: Math.max(0, rowsTo - rows.length) }, () => ['', null] as SideRow)]
  return (
    <table className={cn(tbl.table, 'h-full')}>
      <thead className={tbl.head}>
        <tr>
          <th className={tbl.th}>{heading}</th>
          <th className={tbl.thNum}>{amount}</th>
        </tr>
      </thead>
      <tbody>
        {padded.map(([name, value, ledger], i) => (
          <tr key={`${name}-${i}`} className="h-(--row-h) border-b border-dashed last:border-b-0">
            <td className={tbl.td}>{ledger ? <LedgerLink clientId={clientId} ledger={ledger} name={name} /> : name}</td>
            <td className={tbl.tdNum}>{value}</td>
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

function ProfitAndLossReport({ clientId, fy }: { clientId: string; fy: number }) {
  const r = reportState(useQuery(profitAndLoss(clientId, fy)))
  if (!r.data) return r.node
  const pl = r.data
  if (!pl.income.length && !pl.expenses.length) return <NothingYet clientId={clientId} fy={fy} />
  const profit = pl.net_profit_paise >= 0
  const net = formatPaise(Math.abs(pl.net_profit_paise), { symbol: false })
  const netText = formatPaise(Math.abs(pl.net_profit_paise))
  const left: SideRow[] = pl.expenses.map((e) => [e.name, closingLine(e, 'expense', NO_SYMBOL), e.ledger])
  const right: SideRow[] = pl.income.map((i) => [i.name, closingLine(i, 'income', NO_SYMBOL), i.ledger])
  if (profit) left.push(['Net Profit (carried to Capital)', net])
  else right.push(['Net Loss (carried to Capital)', net])
  const total = formatPaise(Math.max(pl.total_income_paise, pl.total_expenses_paise), { symbol: false })
  const rowsTo = Math.max(left.length, right.length)
  return (
    <ReportFrame clientId={clientId} title="Profit & Loss A/c" footer={pl.footer}>
      <div className="grid gap-4 md:grid-cols-2 md:gap-0 md:divide-x">
        <Side clientId={clientId} heading="Dr · Expenses" amount="Amount ₹" rows={left} rowsTo={rowsTo} total={total} />
        <Side clientId={clientId} heading="Cr · Income" amount="Amount ₹" rows={right} rowsTo={rowsTo} total={total} />
      </div>
      <p className={cn('mt-3 text-sm font-medium', profit ? 'text-success' : 'text-destructive')}>
        {profit ? 'Net Profit' : 'Net Loss'} for the year: {netText}
      </p>
    </ReportFrame>
  )
}

function BalanceSheetReport({ clientId, fy }: { clientId: string; fy: number }) {
  const r = reportState(useQuery(balanceSheet(clientId, fy)))
  if (!r.data) return r.node
  const bs = r.data
  if (!bs.assets.length && !bs.liabilities.length) return <NothingYet clientId={clientId} fy={fy} />
  const liabilities: SideRow[] = bs.liabilities.map((l) => [l.name, closingLine(l, 'liability', NO_SYMBOL), l.ledger])
  liabilities.push([bs.net_profit_paise >= 0 ? 'Add: Net Profit for the year' : 'Less: Net Loss for the year', formatPaise(Math.abs(bs.net_profit_paise), { symbol: false })])
  const assets: SideRow[] = bs.assets.map((a) => [a.name, closingLine(a, 'asset', NO_SYMBOL), a.ledger])
  const rowsTo = Math.max(liabilities.length, assets.length)
  return (
    <ReportFrame clientId={clientId} title="Balance Sheet" footer={bs.footer} period={asAt(fy)}>
      {!bs.balances && (
        <div className="mb-4 flex gap-2 rounded-md border border-destructive/40 bg-destructive-bg p-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
          <span>
            <strong>The Balance Sheet does not balance.</strong> Liabilities and profit are {sideTotal(bs.total_liabilities_and_profit_paise, 'Cr')};
            assets are {sideTotal(bs.total_assets_paise, 'Dr')}.
          </span>
        </div>
      )}
      {bs.suspense_paise !== 0 && (
        <div className="mb-4 rounded-md border border-accent-edge bg-accent p-3 text-sm">
          <strong>{bs.suspense_display}</strong> is in Suspense A/c. Place those transactions in their proper ledgers before finalising.
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-2 md:gap-0 md:divide-x">
        <Side clientId={clientId} heading="Liabilities" amount="Amount ₹" rows={liabilities} rowsTo={rowsTo} total={sideTotal(bs.total_liabilities_and_profit_paise, 'Cr', NO_SYMBOL)} />
        <Side clientId={clientId} heading="Assets" amount="Amount ₹" rows={assets} rowsTo={rowsTo} total={sideTotal(bs.total_assets_paise, 'Dr', NO_SYMBOL)} />
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
  const openingUnconfirmed = !!account && !account.has_opening_balance

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
          {openingUnconfirmed && (
            <div className="flex gap-2 rounded-md border border-accent-edge bg-accent p-3 text-sm">
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-accent-foreground" aria-hidden />
              <span>
                <strong>Opening balance not confirmed.</strong> The books start without this account’s opening balance, so they will differ from the
                statement by that amount. <OpeningLink clientId={clientId} />.
              </span>
            </div>
          )}
          <dl className="grid grid-cols-[1fr_auto] gap-x-6 gap-y-1.5 text-sm">
            <dt>Balance as per books</dt>
            <dd className="num text-right font-medium">{formatDrCr(check.data.ledger_balance_paise)}</dd>
            <dt>Balance as per bank statement</dt>
            <dd className="num text-right font-medium">{formatDrCr(check.data.statement_balance_paise)}</dd>
            <dt className="border-t pt-1.5 font-medium">Difference</dt>
            <dd className={cn('num border-t pt-1.5 text-right font-semibold', check.data.matches ? 'text-success' : 'text-destructive')}>
              {check.data.matches ? formatPaise(0) : formatPaise(Math.abs(check.data.difference_paise))}
              {!check.data.matches && (
                <span className="block text-xs font-normal text-muted-foreground">
                  books are {check.data.difference_paise < 0 ? 'lower' : 'higher'} than the statement
                </span>
              )}
            </dd>
          </dl>
          {openingUnconfirmed && !check.data.matches ? null : <div
            className={cn(
              'flex gap-2 rounded-md p-3 text-sm',
              check.data.matches ? 'border border-success/30 bg-success-bg' : 'border border-accent-edge bg-accent',
            )}
          >
            {check.data.matches ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" /> : <AlertTriangle className="mt-0.5 size-4 shrink-0 text-accent-foreground" />}
            <span>{check.data.explanation}</span>
          </div>}
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
