// A party's statement of account: their ledger, line by line, with a running balance. What would be sent to them.
//
// Read from the same ledger the party's bills are checked against, so it cannot disagree with them. Debits are to the left
// and credits to the right, as in a ledger; the balance carries Dr or Cr. For a supplier the client owes, that is Cr.

import { useQuery } from '@tanstack/react-query'
import { Printer } from 'lucide-react'
import { useMemo, useState } from 'react'
import { partyStatement } from '@/api/queries/bills'
import { Money } from '@/components/ca/Money'
import { ErrorState } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { DateInput } from '@/components/ui/date-input'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Spinner } from '@/components/ui/spinner'
import { financialYearOf, formatDate, formatDrCr, fyRange, parseDate, plural } from '@/lib/format'

export function PartyStatementDialog({
  clientId,
  partyId,
  partyName,
  onClose,
}: {
  clientId: string
  partyId: string
  partyName: string
  onClose: () => void
}) {
  const today = new Date().toISOString().slice(0, 10)
  const [fromText, setFromText] = useState(() => formatDate(fyRange(financialYearOf(today)).from))
  const [toText, setToText] = useState(() => formatDate(today))
  const from = parseDate(fromText)
  const to = parseDate(toText)
  const problem = !from || !to ? 'Enter both dates as DD-MM-YYYY.' : to < from ? 'The end is before the start.' : null

  const statement = useQuery({ ...partyStatement(clientId, partyId, from ?? '', to ?? ''), enabled: !problem })
  const data = statement.data
  const rows = useMemo(() => data?.rows ?? [], [data])

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[92svh] overflow-y-auto sm:max-w-3xl" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{partyName}: statement of account</DialogTitle>
          <DialogDescription>Every posting on this party’s account in the period, with the balance after each.</DialogDescription>
        </DialogHeader>

        <div className="no-print flex flex-wrap items-end gap-3">
          <Field label="From" error={fromText && !from ? 'DD-MM-YYYY' : undefined}>
            {(props) => <DateInput {...props} className="w-36" value={fromText} onChange={(e) => setFromText(e.target.value)} />}
          </Field>
          <Field label="To" error={toText && !to ? 'DD-MM-YYYY' : undefined}>
            {(props) => <DateInput {...props} className="w-36" value={toText} onChange={(e) => setToText(e.target.value)} />}
          </Field>
          <Button variant="secondary" onClick={() => window.print()} disabled={!data}>
            <Printer /> Print
          </Button>
        </div>
        {problem && <p role="alert" className="text-sm text-destructive">{problem}</p>}

        {statement.isPending && !problem ? (
          <Spinner label="Preparing the statement…" />
        ) : statement.isError ? (
          <ErrorState error={statement.error} retry={() => void statement.refetch()} />
        ) : (
          data && (
            <table className="w-full text-sm">
              <caption className="sr-only">
                Statement of account of {partyName}, {formatDate(data.date_from)} to {formatDate(data.date_to)}
              </caption>
              <thead className="border-b text-left text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="py-1.5 font-medium">Date</th>
                  <th scope="col" className="py-1.5 font-medium">Voucher</th>
                  <th scope="col" className="py-1.5 text-right font-medium">Debit (₹)</th>
                  <th scope="col" className="py-1.5 text-right font-medium">Credit (₹)</th>
                  <th scope="col" className="py-1.5 text-right font-medium">Balance (₹)</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b text-muted-foreground">
                  <td className="py-1.5" colSpan={4}>Opening balance on {formatDate(data.date_from)}</td>
                  <td className="py-1.5 text-right tabular-nums">{formatDrCr(data.opening_paise, { symbol: false })}</td>
                </tr>
                {rows.map((row) => (
                  <tr key={`${row.entry}-${row.balance_paise}-${row.debit_paise}-${row.credit_paise}`} className="border-b align-top">
                    <td className="py-1.5 whitespace-nowrap">{formatDate(row.date)}</td>
                    <td className="py-1.5">
                      <div>{row.voucher_type} No. {row.entry_no}</div>
                      {row.narration && <div className="text-xs text-muted-foreground">{row.narration}</div>}
                    </td>
                    <td className="py-1.5 text-right">{row.debit_paise ? <Money display={row.debit_display} symbol={false} /> : <span aria-hidden>—</span>}</td>
                    <td className="py-1.5 text-right">{row.credit_paise ? <Money display={row.credit_display} symbol={false} /> : <span aria-hidden>—</span>}</td>
                    <td className="py-1.5 text-right tabular-nums">{formatDrCr(row.balance_paise, { symbol: false })}</td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td className="py-3 text-center text-muted-foreground" colSpan={5}>Nothing was posted on this account in the period.</td>
                  </tr>
                )}
              </tbody>
              <tfoot className="font-semibold">
                <tr className="border-t-2">
                  <td className="py-1.5" colSpan={2}>Total ({plural(rows.length, 'posting')})</td>
                  <td className="py-1.5 text-right"><Money display={data.total_debit_display} symbol={false} /></td>
                  <td className="py-1.5 text-right"><Money display={data.total_credit_display} symbol={false} /></td>
                  <td className="py-1.5 text-right tabular-nums">{formatDrCr(data.closing_paise, { symbol: false })}</td>
                </tr>
              </tfoot>
            </table>
          )
        )}
      </DialogContent>
    </Dialog>
  )
}
