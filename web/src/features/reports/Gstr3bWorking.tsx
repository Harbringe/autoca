// The GSTR-3B working for one month: the tables a return is filled from, taken from the booked invoices.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { gstr3b, type Gstr3bRow } from '@/api/queries/books'
import { formatPaise } from '@/lib/format'

const money = (paise: number) => (paise === 0 ? '–' : formatPaise(paise, { symbol: false }))

function Row({ label, row, taxable = true }: { label: string; row: Omit<Gstr3bRow, 'taxable_paise'> & { taxable_paise?: number }; taxable?: boolean }) {
  return (
    <tr className="border-t border-border-strong">
      <td className="py-1">{label}</td>
      <td className="py-1 text-right tabular-nums">{taxable ? money(row.taxable_paise ?? 0) : ''}</td>
      <td className="py-1 text-right tabular-nums">{money(row.igst_paise)}</td>
      <td className="py-1 text-right tabular-nums">{money(row.cgst_paise)}</td>
      <td className="py-1 text-right tabular-nums">{money(row.sgst_paise)}</td>
      <td className="py-1 text-right tabular-nums">{money(row.cess_paise)}</td>
    </tr>
  )
}

export function Gstr3bWorking({ clientId, fy }: { clientId: string; fy: number }) {
  const [month, setMonth] = useState(`${fy}-04`)
  const query = useQuery(gstr3b(clientId, month))
  const months = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3].map((m) => `${m >= 4 ? fy : fy + 1}-${String(m).padStart(2, '0')}`)
  const d = query.data

  return (
    <section aria-label="GSTR-3B working" className="grid gap-2 text-sm">
      <div className="flex items-center gap-2">
        <h3 className="font-medium">GSTR-3B working</h3>
        <label htmlFor="gstr3b-month" className="text-muted-foreground">
          Month
        </label>
        <select id="gstr3b-month" className="h-9 rounded-md border border-border-strong bg-transparent px-2" value={month} onChange={(e) => setMonth(e.target.value)}>
          {months.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>
      {d && (
        <>
          <table className="w-full" aria-label="GSTR-3B tables">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="py-1 font-medium">Table</th>
                <th className="py-1 text-right font-medium">Taxable value</th>
                <th className="py-1 text-right font-medium">IGST</th>
                <th className="py-1 text-right font-medium">CGST</th>
                <th className="py-1 text-right font-medium">SGST</th>
                <th className="py-1 text-right font-medium">Cess</th>
              </tr>
            </thead>
            <tbody>
              <Row label="3.1(a) Outward taxable supplies" row={d.outward_taxable} />
              <Row label="3.1(d) Inward supplies on reverse charge" row={d.inward_reverse_charge} />
              <Row label="4(A)(5) ITC: all other" row={d.itc_all_other} taxable={false} />
              <Row label="4(A)(3) ITC: reverse charge" row={d.itc_reverse_charge} taxable={false} />
              <tr className="border-t border-border-strong font-medium">
                <td className="py-1">6.1 Tax payable</td>
                <td />
                <td className="py-1 text-right tabular-nums">{money(d.payable.igst_paise)}</td>
                <td className="py-1 text-right tabular-nums">{money(d.payable.cgst_paise)}</td>
                <td className="py-1 text-right tabular-nums">{money(d.payable.sgst_paise)}</td>
                <td className="py-1 text-right tabular-nums">{money(d.payable.cess_paise)}</td>
              </tr>
            </tbody>
          </table>
          <p className="text-xs text-muted-foreground">
            From {d.counts.sales} sales, {d.counts.purchases} purchases and {d.counts.reverse_charge} reverse-charge purchases. Not in the books, so not here:{' '}
            {d.not_covered.join('; ')}. A negative payable is credit.
          </p>
        </>
      )}
    </section>
  )
}
