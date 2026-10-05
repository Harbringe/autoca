// Payables and Receivables: what the client owes its suppliers, and what its customers owe it, bill by bill, aged.
//
// As at any date: only the settlements that had happened by then count, so last month's report stays what it was. Each party's
// bills are aged from the bill date into 0-30, 31-60, 61-90 and over 90 days. A debit or credit note shows as a negative
// against the bills it reverses, and money held on account or as an advance shows as a negative against the party, so the
// total beside each party is what is truly owed. Read from the same bills the party's ledger is checked against.

import { useQuery } from '@tanstack/react-query'
import { Fragment, useState } from 'react'
import { outstanding } from '@/api/queries/bills'
import { clientDetail } from '@/api/queries/clients'
import { Money } from '@/components/ca/Money'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Card } from '@/components/ui/card'
import { DateInput } from '@/components/ui/date-input'
import { Field } from '@/components/ui/field'
import { Spinner } from '@/components/ui/spinner'
import { PartyStatementDialog } from '@/features/bills/PartyStatementDialog'
import { formatDate, formatPaise, parseDate, plural } from '@/lib/format'

const SIDE = {
  payables: { title: 'Payables', who: 'suppliers' },
  receivables: { title: 'Receivables', who: 'customers' },
} as const

export function OutstandingReport({ clientId, side }: { clientId: string; side: 'payables' | 'receivables' }) {
  const client = useQuery(clientDetail(clientId))
  const [asOfText, setAsOfText] = useState(() => formatDate(new Date().toISOString().slice(0, 10)))
  const asOf = parseDate(asOfText)
  const report = useQuery({ ...outstanding(clientId, side, asOf ?? ''), enabled: !!asOf })
  const [statement, setStatement] = useState<{ id: string; name: string } | null>(null)
  const words = SIDE[side]

  return (
    <Card className="p-5 print:border-0 print:p-0 print:shadow-none">
      <div className="mb-4 text-center">
        <h2 className="text-lg font-semibold text-heading">{client.data?.name}</h2>
        <div className="font-medium">{words.title}: what is owing, by {words.who}</div>
        <div className="text-sm text-muted-foreground">as at {asOf ? formatDate(asOf) : '…'}, aged from the bill date</div>
      </div>

      <div className="no-print mb-4 flex justify-center">
        <Field label="As at" error={asOfText && !asOf ? 'Enter a date as DD-MM-YYYY.' : undefined}>
          {(props) => <DateInput {...props} className="w-40" value={asOfText} onChange={(e) => setAsOfText(e.target.value)} />}
        </Field>
      </div>

      {report.isPending && asOf ? (
        <Spinner label="Preparing the report…" />
      ) : report.isError ? (
        <ErrorState error={report.error} retry={() => void report.refetch()} />
      ) : !report.data || report.data.parties.length === 0 ? (
        <EmptyState title={`Nothing is outstanding to ${words.who}`}>
          {asOf ? `On ${formatDate(asOf)} no bill is unpaid. ` : ''}Book a {side === 'payables' ? 'purchase' : 'sales'} voucher in Purchases & Sales to see it here.
        </EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <caption className="sr-only">{words.title} as at {asOf ? formatDate(asOf) : ''}</caption>
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="py-1.5 text-left font-medium">Party / invoice</th>
                <th scope="col" className="py-1.5 text-left font-medium">Date</th>
                <th scope="col" className="py-1.5 text-right font-medium">Days</th>
                {report.data.buckets.map((b) => (
                  <th key={b} scope="col" className="py-1.5 text-right font-medium">{b} (₹)</th>
                ))}
                <th scope="col" className="py-1.5 text-right font-medium">Total (₹)</th>
              </tr>
            </thead>
            {report.data.parties.map((party) => (
              <tbody key={party.party} className="border-b">
                <tr className="bg-muted/40 font-medium">
                  <th scope="row" className="py-1.5 text-left" colSpan={3}>
                    <button
                      type="button"
                      className="underline decoration-dotted underline-offset-2 hover:decoration-solid print:no-underline"
                      onClick={() => setStatement({ id: party.party, name: party.name })}
                      title="Open this party’s statement of account"
                    >
                      {party.name}
                    </button>
                    {party.gstin_last4 && <span className="ml-2 text-xs font-normal text-muted-foreground">GSTIN …{party.gstin_last4}</span>}
                  </th>
                  {report.data.buckets.map((b) => (
                    <td key={b} className="py-1.5 text-right tabular-nums">{party.bucket_paise[b] ? formatPaise(party.bucket_paise[b]!, { symbol: false }) : '—'}</td>
                  ))}
                  <td className="py-1.5 text-right tabular-nums">{formatPaise(party.total_paise, { symbol: false })}</td>
                </tr>
                {party.bills.map((b) => (
                  <Fragment key={b.bill}>
                    <tr className="text-muted-foreground">
                      <td className="py-1 pl-4">{b.kind_display} {b.reference}</td>
                      <td className="py-1">{formatDate(b.bill_date)}</td>
                      <td className="py-1 text-right tabular-nums">{b.age_days}</td>
                      {report.data.buckets.map((bucket) => (
                        <td key={bucket} className="py-1 text-right tabular-nums">{bucket === b.bucket ? b.open_display.replace('₹', '') : ''}</td>
                      ))}
                      <td className="py-1 text-right tabular-nums">{b.open_display.replace('₹', '')}</td>
                    </tr>
                  </Fragment>
                ))}
                {party.on_account_paise !== 0 && (
                  <tr className="text-muted-foreground">
                    <td className="py-1 pl-4" colSpan={3}>Held on account or as an advance</td>
                    {report.data.buckets.map((b) => <td key={b} />)}
                    <td className="py-1 text-right tabular-nums">{party.on_account_display.replace('₹', '')}</td>
                  </tr>
                )}
              </tbody>
            ))}
            <tfoot className="font-semibold">
              <tr className="border-t-2">
                <td className="py-2" colSpan={3}>Total ({plural(report.data.parties.length, 'party', 'parties')})</td>
                {report.data.buckets.map((b) => (
                  <td key={b} className="py-2 text-right tabular-nums">{formatPaise(report.data.bucket_paise[b] ?? 0, { symbol: false })}</td>
                ))}
                <td className="py-2 text-right"><Money display={report.data.total_display} symbol={false} /></td>
              </tr>
              {report.data.on_account_paise !== 0 && (
                <tr className="font-normal text-muted-foreground">
                  <td className="py-1" colSpan={3 + report.data.buckets.length}>
                    Includes {formatPaise(-report.data.on_account_paise)} held on account or as advances, which lowers the total.
                  </td>
                  <td />
                </tr>
              )}
            </tfoot>
          </table>
        </div>
      )}

      {statement && (
        <PartyStatementDialog clientId={clientId} partyId={statement.id} partyName={statement.name} onClose={() => setStatement(null)} />
      )}
    </Card>
  )
}
