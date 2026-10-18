// The Trial Balance, the Balance Sheet and Profit and Loss in ICAI's format for non-corporate entities (the Balance Sheet and
// Profit & Loss tabs are the same statements as Financial statements, one at a time), the outstanding reports, the inventory
// and the bank reconciliation, for the year chosen at the top. Anything that is not final says so -- a report with rows still
// waiting is Provisional -- and a Trial Balance that does not tally says by how much. Every one prints on a plain page with
// the client, year and date.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { AlertTriangle, CheckCircle2, Printer } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { ReportTab } from './tabs'
import { reconciliation, trialBalance } from '@/api/queries/books'
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
import { BalancePair } from '@/components/charts/BalancePair'
import { EmptyPlot } from '@/components/charts/ColumnChart'
import { tbPair, type Pair } from '@/lib/reportSeries'
import { formatCompact } from '@/lib/format'
import { Picture, ReportSkeleton } from './ReportPicture'
import { asAt, formatDate, formatDrCr, formatPaise, fyLabel, parseDate } from '@/lib/format'
import { useFy } from '@/features/shell/useFy'
import { FinancialStatements } from './FinancialStatements'
import { InventoryReport } from './InventoryReport'
import { OutstandingReport } from './OutstandingReport'
import { isProvisional, OpeningLink, ReportFrame, useUnconfirmedOpenings } from './ReportFrame'
import { cn } from '@/lib/utils'

export type { ReportTab }

export function ReportsScreen({ clientId, report }: { clientId: string; report: ReportTab }) {
  const { fy } = useFy()
  return (
    <div className="grid gap-4 [&>*]:min-w-0">
      {report !== 'recon' && (
        <div className="no-print flex justify-end">
          <Button variant="secondary" onClick={() => window.print()}>
            <Printer /> Print
          </Button>
        </div>
      )}
      {report === 'tb' && <TrialBalanceReport clientId={clientId} fy={fy} />}
      {(report === 'payables' || report === 'receivables') && <OutstandingReport clientId={clientId} side={report} />}
      {(report === 'nce' || report === 'pl' || report === 'bs') && <FinancialStatements clientId={clientId} fy={fy} part={report === 'nce' ? undefined : report} />}
      {report === 'inventory' && <InventoryReport clientId={clientId} fy={fy} />}
      {report === 'recon' && <Reconciliation clientId={clientId} />}
    </div>
  )
}



function reportState<T>(q: { data?: T; isPending: boolean; error: unknown; refetch: () => unknown }) {
  if (q.isPending) return { node: <ReportSkeleton /> }
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
      <Picture title="Debits against credits, by group">
        <BalancePair
          pair={tbPair(tb)}
          agree={`Debits and credits agree at ${formatCompact(tb.total_debit_paise)}`}
          gapWords={(gap) => `${gap > 0 ? 'Debits' : 'Credits'} are higher by ${formatCompact(Math.abs(gap))}`}
        />
      </Picture>
      <div className="relative overflow-x-auto">
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

function NothingYet({ clientId, fy }: { clientId: string; fy: number }) {
  return (
    <EmptyState title={`No entries in FY ${fyLabel(fy)}`}>
      <EmptyPlot line="The chart fills as entries are posted." className="mx-auto mb-3 max-w-sm text-left" />
      Reports are built from posted entries. Post transactions from{' '}
      <Link to="/clients/$clientId/review" params={{ clientId }} search={{ stage: 'unresolved' }} className="underline">
        Review
      </Link>
      , or choose another financial year at the top.
    </EmptyState>
  )
}

/** The books and the bank statement as two bars on one scale, and the gap between them said once. */
function ReconPicture({ books, bank, matches }: { books: number; bank: number; matches: boolean }) {
  const seg = (v: number, tone: 'part1' | 'part3') => [{ key: 'v', label: 'Balance', value: Math.abs(v), valueLabel: formatCompact(Math.abs(v)), fullLabel: formatPaise(Math.abs(v)), tone }]
  const pair: Pair = {
    left: { title: 'As per the books', total: books, segments: seg(books, 'part1'), oppositePaise: 0 },
    right: { title: 'As per the bank statement', total: bank, segments: seg(bank, 'part3'), oppositePaise: 0 },
    gap: books - bank,
    balanced: matches,
  }
  return (
    <BalancePair pair={pair} agree="The books agree with the bank" gapWords={(gap) => `Books are ${gap < 0 ? 'lower' : 'higher'} than the bank by ${formatCompact(Math.abs(gap))}`} />
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
          <ReconPicture books={check.data.ledger_balance_paise} bank={check.data.statement_balance_paise} matches={check.data.matches} />
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
