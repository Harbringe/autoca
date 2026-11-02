// TDS on the bills against TDS in the books, quarter by quarter: what was deducted, what was deposited, and whether each deposit has a
// challan behind it. Reads only.

import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { tdsTieOut } from '@/api/queries/bills'
import { useFy } from '@/features/shell/useFy'
import { formatPaise } from '@/lib/format'

const money = (paise: number) => (paise === 0 ? '–' : formatPaise(paise, { symbol: false }))
const QUARTER = ['', 'Apr–Jun', 'Jul–Sep', 'Oct–Dec', 'Jan–Mar']

export function TdsTieOutCard({ clientId }: { clientId: string }) {
  const { fy } = useFy()
  const query = useQuery(tdsTieOut(clientId, fy))
  const d = query.data
  if (!d || !d.has_ledger) return null

  return (
    <section aria-label="TDS against the books" className="grid gap-2 rounded-md border border-line p-3 text-sm">
      <h2 className="text-[15px] font-semibold text-heading">TDS against the books</h2>
      <p className="flex items-center gap-2">
        {d.agrees ? <CheckCircle2 className="size-4 shrink-0" aria-hidden /> : <AlertTriangle className="size-4 shrink-0" aria-hidden />}
        {d.agrees
          ? `The bills, the TDS Payable ledger and the challans agree. Still to deposit: ${formatPaise(d.still_to_deposit_paise)}.`
          : 'Something does not agree: see the quarters below.'}
      </p>
      {d.without_section_paise > 0 && (
        <p role="status">{formatPaise(d.without_section_paise)} was deducted on bills with no section, so it cannot be reported in the return.</p>
      )}
      <table className="w-full" aria-label="TDS by quarter">
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="py-1 font-medium">Quarter</th>
            <th className="py-1 text-right font-medium">Bills say</th>
            <th className="py-1 text-right font-medium">Ledger credited (bills)</th>
            <th className="py-1 text-right font-medium">Salary and other</th>
            <th className="py-1 text-right font-medium">Deposited</th>
            <th className="py-1 text-right font-medium">With challan</th>
            <th className="py-1 text-right font-medium">Difference</th>
          </tr>
        </thead>
        <tbody>
          {d.quarters.map((q) => (
            <tr key={q.quarter} className="border-t border-border-strong">
              <td className="py-1">{QUARTER[q.quarter]}</td>
              <td className="py-1 text-right tabular-nums">{money(q.bills_paise)}</td>
              <td className="py-1 text-right tabular-nums">{money(q.credited_from_bills_paise)}</td>
              <td className="py-1 text-right tabular-nums">{money(q.credited_other_paise)}</td>
              <td className="py-1 text-right tabular-nums">{money(q.deposited_paise)}</td>
              <td className="py-1 text-right tabular-nums">{money(q.with_challan_paise)}</td>
              <td className="py-1 text-right tabular-nums">{money(q.bills_difference_paise || -q.without_challan_paise)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
