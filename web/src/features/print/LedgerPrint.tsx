// A ledger as an account statement on paper: each posted row with the balance after it, and the closing balance.

import { useQuery } from '@tanstack/react-query'
import { journal, ledgers } from '@/api/queries/books'
import { ErrorState } from '@/components/ca/Page'
import { Spinner } from '@/components/ui/spinner'
import { formatDate } from '@/lib/format'
import { PrintSheet } from './PrintSheet'

const rupees = (paise: number) => (Math.abs(paise) / 100).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const balance = (paise: number) => `${rupees(paise)} ${paise >= 0 ? 'Dr' : 'Cr'}`

export function LedgerPrint({ clientId, ledgerId }: { clientId: string; ledgerId: string }) {
  const entries = useQuery(journal(clientId))
  const all = useQuery(ledgers(clientId))
  if (entries.isPending || all.isPending) return <Spinner />
  if (entries.error) return <ErrorState error={entries.error} retry={() => void entries.refetch()} />
  const name = all.data?.find((l) => l.id === ledgerId)?.name ?? 'Ledger'

  // One row per voucher that touches the ledger, oldest first, with what the other side of it was.
  const rows = entries.data
    .filter((e) => !e.is_superseded && e.lines.some((l) => l.ledger_account === ledgerId))
    .sort((a, b) => a.entry_date.localeCompare(b.entry_date) || a.entry_no - b.entry_no)
    .map((e) => {
      const mine = e.lines.filter((l) => l.ledger_account === ledgerId)
      const signed = mine.reduce((sum, l) => sum + (l.direction === 'DR' ? l.amount_paise : -l.amount_paise), 0)
      const others = [...new Set(e.lines.filter((l) => l.ledger_account !== ledgerId).map((l) => l.ledger_name))]
      return { e, signed, others }
    })

  let running = 0
  const lines = rows.map((row) => {
    running += row.signed
    return { ...row, after: running }
  })

  return (
    <PrintSheet clientId={clientId} title="Account statement">
      <h3 className="text-base font-semibold">{name}</h3>
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-y border-black text-left">
            <th className="py-1 font-medium">Date</th>
            <th className="py-1 font-medium">Particulars</th>
            <th className="py-1 font-medium">Voucher</th>
            <th className="py-1 text-right font-medium">Debit</th>
            <th className="py-1 text-right font-medium">Credit</th>
            <th className="py-1 text-right font-medium">Balance</th>
          </tr>
        </thead>
        <tbody>
          {lines.map(({ e, signed, others, after }) => (
            <tr key={e.id}>
              <td className="whitespace-nowrap py-1 pr-2">{formatDate(e.entry_date)}</td>
              <td className="py-1 pr-2">{e.narration || others.join(', ')}</td>
              <td className="whitespace-nowrap py-1 pr-2">{e.voucher_number || e.entry_no}</td>
              <td className="py-1 text-right tabular-nums">{signed > 0 ? rupees(signed) : ''}</td>
              <td className="py-1 text-right tabular-nums">{signed < 0 ? rupees(signed) : ''}</td>
              <td className="py-1 text-right tabular-nums">{balance(after)}</td>
            </tr>
          ))}
          <tr className="border-y border-black font-semibold">
            <td className="py-1" colSpan={5}>
              Closing balance
            </td>
            <td className="py-1 text-right tabular-nums">{balance(running)}</td>
          </tr>
        </tbody>
      </table>
    </PrintSheet>
  )
}
