// A sales or purchase invoice as it is printed: who it is between, the date and number, the tax split and the total in words.

import { useQuery } from '@tanstack/react-query'
import { bill } from '@/api/queries/bills'
import { ErrorState } from '@/components/ca/Page'
import { Spinner } from '@/components/ui/spinner'
import { amountInWords } from '@/lib/amountInWords'
import { formatDate } from '@/lib/format'
import { PrintSheet } from './PrintSheet'

export function BillPrint({ clientId, billId }: { clientId: string; billId: string }) {
  const q = useQuery(bill(clientId, billId))
  if (q.isPending) return <Spinner />
  if (q.error) return <ErrorState error={q.error} retry={() => void q.refetch()} />
  const b = q.data

  const taxes = [
    { label: 'CGST', paise: b.cgst_paise, shown: b.cgst_display },
    { label: 'SGST', paise: b.sgst_paise, shown: b.sgst_display },
    { label: 'IGST', paise: b.igst_paise, shown: b.igst_display },
    { label: 'Cess', paise: b.cess_paise, shown: b.cess_display },
    { label: 'Round off', paise: b.round_off_paise, shown: b.round_off_display },
  ].filter((t) => t.paise !== 0)

  return (
    <PrintSheet clientId={clientId} title={b.kind_display}>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-1">
        <div>
          <dt className="text-xs uppercase text-gray-600">Party</dt>
          <dd className="font-medium">{b.party_name}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase text-gray-600">Invoice no.</dt>
          <dd className="font-medium">{b.reference}</dd>
        </div>
        <div>
          <dt className="text-xs uppercase text-gray-600">Date</dt>
          <dd>{formatDate(b.bill_date)}</dd>
        </div>
        {b.due_date ? (
          <div>
            <dt className="text-xs uppercase text-gray-600">Due</dt>
            <dd>{formatDate(b.due_date)}</dd>
          </div>
        ) : null}
      </dl>

      <table className="w-full border-collapse">
        <tbody>
          <tr className="border-y border-black">
            <th className="py-1 text-left font-medium">Taxable value</th>
            <td className="py-1 text-right tabular-nums">{b.taxable_display}</td>
          </tr>
          {taxes.map((t) => (
            <tr key={t.label}>
              <th className="py-1 text-left font-normal">{t.label}</th>
              <td className="py-1 text-right tabular-nums">{t.shown}</td>
            </tr>
          ))}
          <tr className="border-y border-black font-semibold">
            <th className="py-1 text-left">Total</th>
            <td className="py-1 text-right tabular-nums">{b.total_display}</td>
          </tr>
        </tbody>
      </table>

      <p className="font-medium">{amountInWords(b.total_paise)}</p>
    </PrintSheet>
  )
}
