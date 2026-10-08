// The Balance Sheet and Statement of Profit and Loss in the form ICAI prescribes for non-corporate entities (Guidance Note
// on Financial Statements of Non-Corporate Entities, 2023): vertical, the previous year beside the current one, a note
// number on every line, and the notes underneath taking each figure apart ledger by ledger.
//
// Where a ledger sits is worked out by the server each year from its group, its name and the sign of its balance, so a party
// that owed money one year and was owed it the next lands on a liability line and then an asset line. When that happens the
// change is listed under the statements, with the disclosure drafted. A ledger can be pinned to a line in Masters.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { AlertTriangle } from 'lucide-react'
import { financialStatements } from '@/api/queries/books'
import type { StatementRow } from '@/api/types'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Spinner } from '@/components/ui/spinner'
import { formatPaise, fyLabel } from '@/lib/format'
import { cn } from '@/lib/utils'
import { ReportFrame } from './ReportFrame'

/** An amount in a statement: a dash for nil, brackets for a negative. */
function figure(paise: number | null | undefined): string {
  if (paise === null || paise === undefined) return ''
  if (paise === 0) return '–'
  const text = formatPaise(Math.abs(paise), { symbol: false })
  return paise < 0 ? `(${text})` : text
}

const LINE_NAMES: Record<string, string> = {
  'EQ.CAP': "Owners' Capital Account",
  'EQ.RES': 'Reserves and surplus',
  'NCL.BORR': 'Long-term borrowings',
  'CL.BORR': 'Short-term borrowings',
  'CL.PAY': 'Trade payables',
  'CL.OTH': 'Other current liabilities',
  'CA.LOANS': 'Short term loans and advances',
  'CA.REC': 'Trade receivables',
  'CA.OTH': 'Other current assets',
}
const lineName = (code: string) => LINE_NAMES[code] ?? code

function StatementTable({ title, rows, current, previous, hasPrevious }: { title: string; rows: StatementRow[]; current: string; previous: string; hasPrevious: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" aria-label={title}>
        <caption className="sr-only">{title}</caption>
        <thead className="border-b-2 text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th scope="col" className="py-2 pr-2 font-semibold">Particulars</th>
            <th scope="col" className="w-14 px-2 py-2 text-center font-semibold">Note</th>
            <th scope="col" className="num w-36 px-2 py-2 text-right font-semibold">{current}</th>
            <th scope="col" className="num w-36 py-2 pl-2 text-right font-semibold">{hasPrevious ? previous : '—'}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const heading = row.kind === 'heading'
            const total = row.kind === 'total'
            return (
              <tr key={row.key} className={cn('border-b border-dashed', total && 'border-b-2 border-solid font-semibold', heading && 'border-b-0')}>
                <td className={cn('py-1.5 pr-2', heading && 'pt-3 font-semibold text-heading')} style={{ paddingLeft: `${row.level * 1.25}rem` }}>
                  {row.label}
                </td>
                <td className="px-2 text-center text-muted-foreground">
                  {row.note ? (
                    <a href={`#note-${row.note}`} className="underline underline-offset-2 hover:text-foreground" aria-label={`Note ${row.note}`}>
                      {row.note}
                    </a>
                  ) : null}
                </td>
                <td className="num px-2 text-right">{heading ? '' : figure(row.current_paise)}</td>
                <td className="num pl-2 text-right text-muted-foreground">{heading || !hasPrevious ? '' : figure(row.previous_paise)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function FinancialStatements({ clientId, fy }: { clientId: string; fy: number }) {
  const q = useQuery(financialStatements(clientId, fy))
  if (q.isPending) return <Spinner label="Preparing the statements…" />
  if (q.error) return <ErrorState error={q.error} retry={() => void q.refetch()} />
  const s = q.data
  const filled = s.balance_sheet.some((r) => (r.current_paise ?? 0) !== 0) || s.profit_and_loss.some((r) => (r.current_paise ?? 0) !== 0)
  if (!filled) {
    return (
      <EmptyState title={`No entries in FY ${fyLabel(fy)}`}>
        The statements are built from posted entries. Post transactions from{' '}
        <Link to="/clients/$clientId/review" params={{ clientId }} search={{ stage: 'unresolved' }} className="underline">
          Review
        </Link>
        , or choose another financial year at the top.
      </EmptyState>
    )
  }
  const end = `31 March ${fy + 1}`
  const prevEnd = `31 March ${fy}`
  return (
    <div className="grid gap-4">
      <ReportFrame clientId={clientId} title="Balance Sheet" footer={s.footer} period={`as at ${end}`}>
        {!s.balances && (
          <div className="mb-4 flex gap-2 rounded-md border border-destructive/40 bg-destructive-bg p-3 text-sm">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
            <span><strong>The Balance Sheet does not balance.</strong> Something bypassed the journal; the Trial Balance shows by how much.</span>
          </div>
        )}
        {s.suspense_paise !== 0 && (
          <div className="mb-4 rounded-md border border-accent-edge bg-accent p-3 text-sm">
            <strong>{formatPaise(Math.abs(s.suspense_paise))}</strong> is in Suspense A/c and is shown under {s.suspense_paise > 0 ? 'Other current assets' : 'Other current liabilities'}.
            Place those transactions in their proper ledgers before finalising.
          </div>
        )}
        <p className="mb-2 text-xs text-muted-foreground">(Amount in Rs.)</p>
        <StatementTable title="Balance Sheet" rows={s.balance_sheet} current={end} previous={prevEnd} hasPrevious={s.has_previous} />
      </ReportFrame>

      <ReportFrame clientId={clientId} title="Statement of Profit and Loss" footer={s.footer} period={`for the year ended ${end}`}>
        <p className="mb-2 text-xs text-muted-foreground">(Amount in Rs.)</p>
        <StatementTable title="Statement of Profit and Loss" rows={s.profit_and_loss} current={end} previous={prevEnd} hasPrevious={s.has_previous} />
      </ReportFrame>

      {s.regroupings.length > 0 && (
        <section aria-label="Regrouping" className="rounded-lg border border-accent-edge bg-accent p-4 text-sm print:break-inside-avoid">
          <h2 className="mb-1 font-semibold text-heading">Regrouping of previous year figures</h2>
          <p className="mb-2 text-muted-foreground">
            These ledgers changed from a debit to a credit balance, or the other way, so they are presented on a different line from last year. Profit is not affected.
          </p>
          <ul className="grid gap-2">
            {s.regroupings.map((g) => (
              <li key={g.ledger}>
                <Link to="/clients/$clientId/ledgers" params={{ clientId }} search={{ ledger: g.ledger }} className="font-medium underline underline-offset-2">
                  {g.name}
                </Link>
                : {formatPaise(Math.abs(g.previous_paise))} last year shown under {lineName(g.previous_line)}; {formatPaise(Math.abs(g.current_paise))} this year under {lineName(g.current_line)}.
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-label="Notes" className="grid gap-4">
        <h2 className="text-base font-semibold text-heading">Notes forming part of the financial statements</h2>
        {s.notes.map((note) => (
          <article key={note.number} id={`note-${note.number}`} className="scroll-mt-20 rounded-lg border bg-card p-4 print:break-inside-avoid">
            <h3 className="mb-2 text-sm font-semibold text-heading">
              Note {note.number} · {note.title}
            </h3>
            <table className="w-full text-sm">
              <thead className="border-b text-left text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="py-1 font-medium">Particulars</th>
                  <th scope="col" className="num w-36 px-2 py-1 text-right font-medium">{end}</th>
                  <th scope="col" className="num w-36 py-1 pl-2 text-right font-medium">{s.has_previous ? prevEnd : '—'}</th>
                </tr>
              </thead>
              <tbody>
                {note.rows.map((row, i) => (
                  <tr key={`${row.label}-${i}`} className="border-b border-dashed">
                    <td className="py-1.5">
                      {row.ledger ? (
                        <Link to="/clients/$clientId/ledgers" params={{ clientId }} search={{ ledger: row.ledger }} className="hover:underline">
                          {row.label}
                        </Link>
                      ) : (
                        row.label
                      )}
                    </td>
                    <td className="num px-2 text-right">{figure(row.current_paise)}</td>
                    <td className="num pl-2 text-right text-muted-foreground">{s.has_previous ? figure(row.previous_paise) : ''}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="font-semibold">
                  <td className="py-1.5">Total</td>
                  <td className="num px-2 text-right">{figure(note.total_current_paise)}</td>
                  <td className="num pl-2 text-right">{s.has_previous ? figure(note.total_previous_paise) : ''}</td>
                </tr>
              </tfoot>
            </table>
          </article>
        ))}
      </section>
    </div>
  )
}
