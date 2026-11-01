// A voucher as it is printed: number, date, the debit and credit lines, the narration and the amount in words.

import { useQuery } from '@tanstack/react-query'
import { raw } from '@/api/client'
import { V1 } from '@/api/queries/clients'
import type { JournalEntry } from '@/api/types'
import { ErrorState } from '@/components/ca/Page'
import { Spinner } from '@/components/ui/spinner'
import { amountInWords } from '@/lib/amountInWords'
import { formatDate } from '@/lib/format'
import { PrintSheet } from './PrintSheet'

const TITLE: Record<string, string> = { PAYMENT: 'Payment voucher', RECEIPT: 'Receipt voucher', JOURNAL: 'Journal voucher', CONTRA: 'Contra voucher' }

export function VoucherPrint({ clientId, entryId }: { clientId: string; entryId: string }) {
  const q = useQuery({ queryKey: ['print', 'entry', clientId, entryId], queryFn: () => raw.get<JournalEntry>(`${V1}/journal-entries/${entryId}/`) })
  if (q.isPending) return <Spinner />
  if (q.error) return <ErrorState error={q.error} retry={() => void q.refetch()} />
  const e = q.data
  const name = e.voucher_number || String(e.entry_no)

  return (
    <PrintSheet clientId={clientId} title={TITLE[e.voucher_type] ?? `${e.voucher_type.charAt(0)}${e.voucher_type.slice(1).toLowerCase().replace(/_/g, ' ')} voucher`}>
      <dl className="flex justify-between">
        <div>
          <dt className="text-xs uppercase text-gray-600">Voucher no.</dt>
          <dd className="font-medium">{name}</dd>
        </div>
        <div className="text-right">
          <dt className="text-xs uppercase text-gray-600">Date</dt>
          <dd>{formatDate(e.entry_date)}</dd>
        </div>
      </dl>
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-y border-black text-left">
            <th className="py-1 font-medium">Particulars</th>
            <th className="py-1 text-right font-medium">Debit</th>
            <th className="py-1 text-right font-medium">Credit</th>
          </tr>
        </thead>
        <tbody>
          {e.lines.map((l) => (
            <tr key={l.id}>
              <td className="py-1">
                {l.ledger_name}
                {l.party_name ? <span className="text-gray-600"> ({l.party_name})</span> : null}
              </td>
              <td className="py-1 text-right tabular-nums">{l.direction === 'DR' ? l.amount_display : ''}</td>
              <td className="py-1 text-right tabular-nums">{l.direction === 'CR' ? l.amount_display : ''}</td>
            </tr>
          ))}
          <tr className="border-y border-black font-semibold">
            <td className="py-1">Total</td>
            <td className="py-1 text-right tabular-nums">{e.total_display}</td>
            <td className="py-1 text-right tabular-nums">{e.total_display}</td>
          </tr>
        </tbody>
      </table>
      {e.narration ? <p>{e.narration}</p> : null}
      <p className="font-medium">{amountInWords(e.total_paise)}</p>
    </PrintSheet>
  )
}
