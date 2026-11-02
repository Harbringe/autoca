// The stock movements no invoice carries (opening stock, a count found different, a move between godowns), listed under the Day Book
// the way Tally lists its stock journals: they are in the stock register and carry no accounting entry of their own.

import { useQuery } from '@tanstack/react-query'
import { raw } from '@/api/client'
import { V1 } from '@/api/queries/clients'
import { formatDate } from '@/lib/format'

interface Row {
  id: string
  kind: string
  kind_display: string
  entry_date: string
  direction: 'IN' | 'OUT'
  name: string
  unit: string
  quantity: string
  note: string
}

const plain = (q: string) => (q.includes('.') ? q.replace(/0+$/, '').replace(/\.$/, '') : q)

export function StockVouchers({ clientId, fy }: { clientId: string; fy: number }) {
  const rows = useQuery({
    queryKey: ['stock-entries', clientId],
    queryFn: () => raw.get<{ results: Row[] }>(`${V1}/clients/${clientId}/stock-entries/`),
  })
  const from = `${fy}-04-01`
  const to = `${fy + 1}-03-31`
  const mine = (rows.data?.results ?? []).filter((r) => r.kind !== 'TALLY' && r.entry_date >= from && r.entry_date <= to)
  if (mine.length === 0) return null

  return (
    <section aria-label="Stock vouchers" className="rounded-md border border-line p-3 text-sm">
      <h3 className="font-medium">Stock vouchers</h3>
      <p className="mt-1 text-xs text-muted-foreground">
        Opening stock, counts and moves between godowns. They are in the stock register and carry no accounting entry; the year&apos;s closing stock
        reaches the books through the closing-stock figure.
      </p>
      <table className="mt-2 w-full">
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="py-1 font-medium">Date</th>
            <th className="py-1 font-medium">Type</th>
            <th className="py-1 font-medium">Item</th>
            <th className="py-1 text-right font-medium">Quantity</th>
            <th className="py-1 pl-3 font-medium">Note</th>
          </tr>
        </thead>
        <tbody>
          {mine.map((r) => (
            <tr key={r.id} className="border-t border-border-strong">
              <td className="py-1">{formatDate(r.entry_date)}</td>
              <td className="py-1">{r.kind_display}</td>
              <td className="py-1">{r.name}</td>
              <td className="py-1 text-right tabular-nums">
                {r.direction === 'IN' ? '+' : '−'}
                {plain(r.quantity)} {r.unit}
              </td>
              <td className="py-1 pl-3 text-muted-foreground">{r.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
