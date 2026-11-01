// A ledger as an account statement on paper: each posted row with the balance after it, and the closing balance.

import { useQuery } from '@tanstack/react-query'
import { ledgerRows, ledgers } from '@/api/queries/books'
import { ErrorState } from '@/components/ca/Page'
import { Spinner } from '@/components/ui/spinner'
import { formatDate } from '@/lib/format'
import { PrintSheet } from './PrintSheet'

const rupees = (paise: number) => (Math.abs(paise) / 100).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const balance = (paise: number) => `${rupees(paise)} ${paise >= 0 ? 'Dr' : 'Cr'}`

export function LedgerPrint({ clientId, ledgerId }: { clientId: string; ledgerId: string }) {
  const rows = useQuery(ledgerRows(clientId, ledgerId))
  const all = useQuery(ledgers(clientId))
  if (rows.isPending || all.isPending) return <Spinner />
  if (rows.error) return <ErrorState error={rows.error} retry={() => void rows.refetch()} />
  const name = all.data?.find((l) => l.id === ledgerId)?.name ?? 'Ledger'
  const posted = rows.data.filter((r) => r.is_posted).sort((a, b) => a.value_date.localeCompare(b.value_date))

  let running = 0
  const lines = posted.map((r) => {
    running += r.is_debit ? r.amount_paise : -r.amount_paise
    return { r, after: running }
  })

  return (
    <PrintSheet clientId={clientId} title="Account statement">
      <h3 className="text-base font-semibold">{name}</h3>
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-y border-black text-left">
            <th className="py-1 font-medium">Date</th>
            <th className="py-1 font-medium">Particulars</th>
            <th className="py-1 text-right font-medium">Debit</th>
            <th className="py-1 text-right font-medium">Credit</th>
            <th className="py-1 text-right font-medium">Balance</th>
          </tr>
        </thead>
        <tbody>
          {lines.map(({ r, after }) => (
            <tr key={r.id}>
              <td className="py-1 pr-2 whitespace-nowrap">{formatDate(r.value_date)}</td>
              <td className="py-1 pr-2">
                <span>{r.narration || r.counterparty}</span>
              </td>
              <td className="py-1 text-right tabular-nums">{r.is_debit ? r.amount_display : ''}</td>
              <td className="py-1 text-right tabular-nums">{r.is_debit ? '' : r.amount_display}</td>
              <td className="py-1 text-right tabular-nums">{balance(after)}</td>
            </tr>
          ))}
          <tr className="border-y border-black font-semibold">
            <td className="py-1" colSpan={4}>
              Closing balance
            </td>
            <td className="py-1 text-right tabular-nums">{balance(running)}</td>
          </tr>
        </tbody>
      </table>
    </PrintSheet>
  )
}
