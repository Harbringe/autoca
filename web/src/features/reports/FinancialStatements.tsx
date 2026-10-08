// The Balance Sheet and Statement of Profit and Loss in the form ICAI prescribes for non-corporate entities (Guidance Note
// on Financial Statements of Non-Corporate Entities, 2023): vertical, the previous year beside the current one, a note
// number on every line, and the notes underneath taking each figure apart ledger by ledger.
//
// Where a ledger sits is worked out by the server each year from its group, its name and the sign of its balance, so a party
// that owed money one year and was owed it the next lands on a liability line and then an asset line. When that happens the
// change is listed under the statements, with the disclosure drafted. A ledger can be pinned to a line in Masters.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { AlertTriangle, Download, Settings2 } from 'lucide-react'
import { Fragment, useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { financialStatements } from '@/api/queries/books'
import { useInvalidateClient, V1 } from '@/api/queries/clients'
import type { StatementRow, Statements } from '@/api/types'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/controls'
import { Spinner } from '@/components/ui/spinner'
import { formatPaise, fyLabel } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { ReportFrame } from './ReportFrame'
import { StatementDetails } from './StatementDetails'

/** An amount in a statement: a dash for nil, brackets for a negative, in the unit the figures are rounded to. */
function figure(paise: number | null | undefined, unit = 100): string {
  if (paise === null || paise === undefined) return ''
  if (paise === 0) return '–'
  const text =
    unit === 100
      ? formatPaise(Math.abs(paise), { symbol: false })
      : new Intl.NumberFormat('en-IN', { minimumFractionDigits: unit >= 10_000_000 ? 2 : 0, maximumFractionDigits: unit >= 10_000_000 ? 2 : 0 }).format(Math.abs(paise) / unit)
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

function StatementTable({ title, rows, current, previous, hasPrevious, unit }: { title: string; rows: StatementRow[]; current: string; previous: string; hasPrevious: boolean; unit: number }) {
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
                <td className="num px-2 text-right">{heading ? '' : figure(row.current_paise, unit)}</td>
                <td className="num pl-2 text-right text-muted-foreground">{heading || !hasPrevious ? '' : figure(row.previous_paise, unit)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function ScheduleTable({ schedule, unit }: { schedule: Statements['schedules'][number]; unit: number }) {
  return (
    <article className="overflow-x-auto rounded-lg border bg-card p-4 print:break-inside-avoid" aria-label={schedule.title}>
      <h3 className="mb-2 text-sm font-semibold text-heading">
        Note {schedule.note} · {schedule.title}
      </h3>
      <table className="w-full text-sm">
        <thead className="border-b text-left text-xs text-muted-foreground">
          <tr>
            <th scope="col" className="py-1 font-medium">Particulars</th>
            {schedule.columns.map((c) => (
              <th key={c} scope="col" className="num w-36 px-2 py-1 text-right font-medium">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {schedule.rows.map((r, i) => (
            <tr key={i} className={cn('border-b border-dashed', r.kind === 'total' && 'border-b-2 border-solid font-semibold')}>
              <td className={cn('py-1.5', r.kind === 'heading' && 'pt-3 font-semibold text-heading')}>{r.label}</td>
              {r.values.map((v, j) => (
                <td key={j} className="num px-2 text-right">{r.kind === 'heading' ? '' : figure(v, unit)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </article>
  )
}

export function FinancialStatements({ clientId, fy }: { clientId: string; fy: number }) {
  const q = useQuery(financialStatements(clientId, fy))
  const { can } = useSession()
  const [editing, setEditing] = useState(false)
  const invalidate = useInvalidateClient(clientId)
  async function pin(ledger: string, section: string) {
    try {
      await raw.patch(`${V1}/clients/${clientId}/ledgers/${ledger}/`, { nce_section: section })
      await invalidate()
      toast.success('Placed')
    } catch (e) {
      toast.error(messageOf(e))
    }
  }
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
  const unit = s.unit_paise
  return (
    <div className="grid gap-4">
      <div className="no-print flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">Presented in ICAI’s format for non-corporate entities.</p>
        <div className="flex gap-2">
          {can('ledger.manage') && (
            <Button type="button" size="sm" variant="outline" onClick={() => setEditing(true)}>
              <Settings2 /> Statement details
            </Button>
          )}
          <Button asChild size="sm" variant="outline">
            <a href={`${V1}/clients/${clientId}/reports/financial-statements/export/?fy=${fy}`}>
              <Download /> Download Excel
            </a>
          </Button>
        </div>
      </div>
      {editing && <StatementDetails clientId={clientId} fy={fy} onClose={() => setEditing(false)} />}
      {s.warnings.length > 0 && (
        <ul className="no-print grid gap-1 rounded-md border border-accent-edge bg-accent p-3 text-sm" aria-label="To settle before issuing">
          {s.warnings.map((w) => (
            <li key={w} className="flex gap-2">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
              <span>{w}</span>
            </li>
          ))}
        </ul>
      )}
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
        <p className="mb-2 text-xs text-muted-foreground">(Amount in {s.unit_label})</p>
        <StatementTable title="Balance Sheet" rows={s.balance_sheet} current={end} previous={prevEnd} hasPrevious={s.has_previous} unit={s.unit_paise} />
      </ReportFrame>

      <ReportFrame clientId={clientId} title="Statement of Profit and Loss" footer={s.footer} period={`for the year ended ${end}`}>
        <p className="mb-2 text-xs text-muted-foreground">(Amount in {s.unit_label})</p>
        <StatementTable title="Statement of Profit and Loss" rows={s.profit_and_loss} current={end} previous={prevEnd} hasPrevious={s.has_previous} unit={s.unit_paise} />
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
        <article id="note-1" className="scroll-mt-20 rounded-lg border bg-card p-4 print:break-inside-avoid">
          <h3 className="mb-2 text-sm font-semibold text-heading">Note 1 · Brief about the entity</h3>
          <p className="whitespace-pre-line text-sm">{s.about || <span className="text-muted-foreground">Not written yet.</span>}</p>
        </article>
        <article id="note-2" className="scroll-mt-20 rounded-lg border bg-card p-4 print:break-inside-avoid">
          <h3 className="mb-2 text-sm font-semibold text-heading">Note 2 · Significant accounting policies</h3>
          <p className="whitespace-pre-line text-sm">{s.policies || <span className="text-muted-foreground">Not written yet.</span>}</p>
          <p className="mt-2 text-sm text-muted-foreground">{s.size_statement}</p>
        </article>
        {s.capital && (
          <article id="capital-table" className="scroll-mt-20 overflow-x-auto rounded-lg border bg-card p-4 print:break-inside-avoid">
            <h3 className="mb-2 text-sm font-semibold text-heading">Note 3 · {s.capital_title}, partner by partner</h3>
            <table className="w-full min-w-[48rem] text-sm">
              <thead className="border-b text-left text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="py-1 font-medium">Name</th>
                  {['Share %', 'Opening', 'Introduced', 'Remuneration', 'Interest', 'Withdrawals', 'Share of profit/(loss)', 'Closing'].map((h) => (
                    <th key={h} scope="col" className="num px-1 py-1 text-right font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {s.capital.rows.map((p) => (
                  <tr key={p.name} className="border-b border-dashed">
                    <td className="py-1.5">{p.name}</td>
                    <td className="num px-1 text-right">{(p.share_bp / 100).toFixed(2)}</td>
                    {[p.opening_paise, p.introduced_paise, p.remuneration_paise, p.interest_paise, p.withdrawals_paise, p.profit_share_paise, p.closing_paise].map((v, i) => (
                      <td key={i} className="num px-1 text-right">{figure(v, unit)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="font-semibold">
                  <td className="py-1.5">Total</td>
                  <td />
                  {(['opening_paise', 'introduced_paise', 'remuneration_paise', 'interest_paise', 'withdrawals_paise', 'profit_share_paise', 'closing_paise'] as const).map((f) => (
                    <td key={f} className="num px-1 text-right">{figure(s.capital!.rows.reduce((sum, p) => sum + p[f], 0), unit)}</td>
                  ))}
                </tr>
                {s.has_previous && s.capital.previous.length > 0 && (
                  <tr className="text-muted-foreground">
                    <td className="py-1.5">Previous year</td>
                    <td />
                    {(['opening_paise', 'introduced_paise', 'remuneration_paise', 'interest_paise', 'withdrawals_paise', 'profit_share_paise', 'closing_paise'] as const).map((f) => (
                      <td key={f} className="num px-1 text-right">{figure(s.capital!.previous.reduce((sum, p) => sum + p[f], 0), unit)}</td>
                    ))}
                  </tr>
                )}
              </tfoot>
            </table>
          </article>
        )}
        {s.notes.map((note) => (
          <Fragment key={note.number}>
          <article id={`note-${note.number}`} className="scroll-mt-20 rounded-lg border bg-card p-4 print:break-inside-avoid">
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
                  <Fragment key={`${row.label}-${i}`}>
                    {row.section && row.section !== note.rows[i - 1]?.section && (
                      <tr>
                        <th scope="rowgroup" colSpan={3} className="pb-1 pt-3 text-left text-xs font-semibold italic text-muted-foreground">{row.section}</th>
                      </tr>
                    )}
                    <tr className="border-b border-dashed">
                      <td className={cn('py-1.5', row.section && 'pl-4')}>
                        {row.ledger ? (
                          <Link to="/clients/$clientId/ledgers" params={{ clientId }} search={{ ledger: row.ledger }} className="hover:underline">
                            {row.label}
                          </Link>
                        ) : (
                          row.label
                        )}
                        {row.guessed && row.ledger && can('ledger.manage') && (
                          <Select
                            aria-label={`Sub-head for ${row.label}`}
                            className="ml-2 inline-block h-7 w-auto py-0 text-xs no-print"
                            value=""
                            onChange={(e) => e.target.value && void pin(row.ledger as string, e.target.value)}
                          >
                            <option value="">Placed by guess · choose</option>
                            {note.choices.map((c) => (
                              <option key={c} value={c}>{c}</option>
                            ))}
                          </Select>
                        )}
                      </td>
                      <td className="num px-2 text-right">{figure(row.current_paise, unit)}</td>
                      <td className="num pl-2 text-right text-muted-foreground">{s.has_previous ? figure(row.previous_paise, unit) : ''}</td>
                    </tr>
                  </Fragment>
                ))}
              </tbody>
              <tfoot>
                <tr className="font-semibold">
                  <td className="py-1.5">Total</td>
                  <td className="num px-2 text-right">{figure(note.total_current_paise, unit)}</td>
                  <td className="num pl-2 text-right">{s.has_previous ? figure(note.total_previous_paise, unit) : ''}</td>
                </tr>
              </tfoot>
            </table>
          </article>
          {s.schedules.filter((sc) => sc.note === note.number).map((sc) => (
            <ScheduleTable key={sc.title} schedule={sc} unit={unit} />
          ))}
          </Fragment>
        ))}
      </section>
    </div>
  )
}
