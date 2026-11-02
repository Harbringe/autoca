// GST on the invoices against GST in the books, head by head, with the month-by-month working a 3B return starts from.

import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { gstTieOut } from '@/api/queries/books'
import { ErrorState } from '@/components/ca/Page'
import { formatPaise } from '@/lib/format'
import { Gstr1Working } from './Gstr1Working'
import { Gstr3bWorking } from './Gstr3bWorking'
import { ReportSkeleton } from './ReportPicture'

const money = (paise: number) => (paise === 0 ? '' : formatPaise(paise, { symbol: false }))
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function GstTieOutReport({ clientId, fy }: { clientId: string; fy: number }) {
  const query = useQuery(gstTieOut(clientId, fy))
  if (query.isPending) return <ReportSkeleton />
  if (query.error) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  const data = query.data
  const num = (row: Record<string, string | number>, key: string) => Number(row[key] ?? 0)

  if (data.heads.length === 0 && data.months.length === 0) {
    return <p className="text-sm text-muted-foreground">No sales or purchase invoices with GST this year.</p>
  }

  return (
    <div className="grid gap-4 text-sm">
      <p className="flex items-center gap-2">
        {data.agrees ? <CheckCircle2 className="size-4 shrink-0" aria-hidden /> : <AlertTriangle className="size-4 shrink-0" aria-hidden />}
        {data.agrees
          ? 'The tax on the invoices is what the GST ledgers carry.'
          : 'The GST ledgers do not carry what the invoices say. The difference is a journal posted to a GST ledger by hand, or an invoice booked with other tax.'}
      </p>

      <table className="w-full" aria-label="GST on the invoices against the books">
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="py-1 font-medium">Tax</th>
            <th className="py-1 text-right font-medium">On the invoices</th>
            <th className="py-1 text-right font-medium">In the books</th>
            <th className="py-1 text-right font-medium">Difference</th>
          </tr>
        </thead>
        <tbody>
          {data.heads.map((h) => (
            <tr key={`${h.side}-${h.head}`} className="border-t border-border-strong">
              <td className="py-1">
                {h.side === 'output' ? 'Output' : 'Input'} {h.head}
              </td>
              <td className="py-1 text-right tabular-nums">{money(h.invoices_paise)}</td>
              <td className="py-1 text-right tabular-nums">{money(h.books_paise)}</td>
              <td className="py-1 text-right tabular-nums">{money(h.difference_paise)}</td>
            </tr>
          ))}
          <tr className="border-t border-border-strong font-medium">
            <td className="py-1">{data.net.payable_paise >= 0 ? 'Payable' : 'Carried forward as credit'}</td>
            <td className="py-1 text-right tabular-nums" colSpan={3}>
              {formatPaise(Math.abs(data.net.payable_paise), { symbol: false })}
            </td>
          </tr>
        </tbody>
      </table>

      <table className="w-full" aria-label="Month by month">
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="py-1 font-medium">Month</th>
            <th className="py-1 text-right font-medium">Outward taxable</th>
            <th className="py-1 text-right font-medium">Output tax</th>
            <th className="py-1 text-right font-medium">Inward taxable</th>
            <th className="py-1 text-right font-medium">Input tax</th>
          </tr>
        </thead>
        <tbody>
          {data.months.map((m) => {
            const [, mm] = String(m.month).split('-')
            const tax = (side: string) => ['cgst', 'sgst', 'igst', 'cess'].reduce((s, h) => s + num(m, `${side}_${h}_paise`), 0)
            return (
              <tr key={String(m.month)} className="border-t border-border-strong">
                <td className="py-1">{MONTHS[Number(mm) - 1]}</td>
                <td className="py-1 text-right tabular-nums">{money(num(m, 'outward_taxable_paise'))}</td>
                <td className="py-1 text-right tabular-nums">{money(tax('output'))}</td>
                <td className="py-1 text-right tabular-nums">{money(num(m, 'inward_taxable_paise'))}</td>
                <td className="py-1 text-right tabular-nums">{money(tax('input'))}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <Gstr3bWorking clientId={clientId} fy={fy} />
      <Gstr1Working clientId={clientId} fy={fy} />
    </div>
  )
}
