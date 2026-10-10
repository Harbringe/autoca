// Stock by item and month: inwards, outwards and closing, in the shape of Tally's Stock Item Monthly Summary.
//
// AutoCA books vouchers, not stock, so the movements are the lines of the invoices behind booked purchases (in) and sales
// (out). The report says plainly how many bills it could not use, because a missing bill is a wrong closing figure.

import { useQuery } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { useState } from 'react'
import { inventoryReport } from '@/api/queries/books'
import type { InventoryItem } from '@/api/types'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Select } from '@/components/ui/controls'
import { Spinner } from '@/components/ui/spinner'
import { formatPaise, plural } from '@/lib/format'
import { normaliseName } from '@/lib/names'
import { Button } from '@/components/ui/button'
import { ReportFrame } from './ReportFrame'
import { StockEntries } from './StockEntries'

const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

function monthLabel(month: string): string {
  const [, m] = month.split('-')
  return MONTH_NAMES[Number(m) - 1] ?? month
}

/** A quantity with its unit, "60 BAG"; negative ones in brackets as the books show a shortfall. */
function qty(value: string, unit: string): string {
  if (!value || value === '0') return ''
  const negative = value.startsWith('-')
  const text = `${negative ? value.slice(1) : value}${unit ? ` ${unit}` : ''}`
  return negative ? `(${text})` : text
}

const money = (paise: number) => (paise === 0 ? '' : formatPaise(paise, { symbol: false }))

export function InventoryReport({ clientId, fy }: { clientId: string; fy: number }) {
  const query = useQuery(inventoryReport(clientId, fy))
  const [picked, setPicked] = useState('')
  const [recording, setRecording] = useState(false)
  if (query.isPending) return <Spinner label="Preparing the report…" />
  if (query.error) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  const report = query.data
  const shown = picked ? report.items.filter((i) => i.name === picked) : report.items

  return (
    <ReportFrame clientId={clientId} title="Inventory: stock item monthly summary" footer={report.footer}>
      {(report.bills_left_out > 0 || report.lines_without_value > 0) && (
        <div className="mb-4 flex gap-2 rounded-md border border-accent-edge bg-accent p-3 text-sm">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <div className="grid gap-1">
            {report.bills_left_out > 0 && (
              <span>
                <strong>{plural(report.bills_left_out, 'purchase or sale')}</strong> this year {report.bills_left_out === 1 ? 'has' : 'have'} no invoice
                lines with a quantity, so {report.bills_left_out === 1 ? 'it adds' : 'they add'} nothing here
                {report.left_out_examples.length ? ` (${report.left_out_examples.join(', ')})` : ''}. Upload the invoice, or key the quantities on its Itemizations tab.
              </span>
            )}
            {report.lines_without_value > 0 && (
              <span>{plural(report.lines_without_value, 'line')} {report.lines_without_value === 1 ? 'has' : 'have'} a quantity but no amount, so {report.lines_without_value === 1 ? 'it moves' : 'they move'} stock without value.</span>
            )}
          </div>
        </div>
      )}

      <div className="no-print mb-3 flex justify-end">
        <Button variant="outline" size="sm" onClick={() => setRecording(true)}>Opening stock and adjustments</Button>
      </div>
      {recording && <StockEntries clientId={clientId} fy={fy} onClose={() => setRecording(false)} />}

      {report.items.length === 0 ? (
        <EmptyState title="No stock movements yet">
          Stock is taken from the lines of purchase and sales invoices. Upload invoices (with their lines read) and they appear here.
        </EmptyState>
      ) : (
        <div className="grid gap-6">
          <div className="no-print flex flex-wrap items-center gap-3 text-sm">
            <label htmlFor="inventory-item" className="font-medium">Item</label>
            <Select id="inventory-item" className="max-w-sm" value={picked} onChange={(e) => setPicked(e.target.value)}>
              <option value="">All items ({report.items.length})</option>
              {report.items.map((i) => (
                <option key={i.name} value={i.name}>{normaliseName(i.name)}</option>
              ))}
            </Select>
            <span className="text-muted-foreground">Values are at weighted-average cost. {plural(report.bills_counted, 'bill')} counted.</span>
          </div>
          {shown.map((item) => (
            <ItemBlock key={item.name} item={item} />
          ))}
        </div>
      )}
    </ReportFrame>
  )
}

function ItemBlock({ item }: { item: InventoryItem }) {
  const unit = item.unit
  return (
    <section aria-label={item.name} className="overflow-x-auto print:break-inside-avoid">
      <h3 className="mb-1 font-semibold text-heading">{normaliseName(item.name)}</h3>
      <table className="w-full min-w-[44rem] text-sm" aria-label={`Monthly summary of ${item.name}`}>
        <thead className="border-b-2 text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th rowSpan={2} scope="col" className="py-1 pr-2 font-semibold">Particulars</th>
            <th colSpan={2} scope="colgroup" className="px-2 text-center font-semibold">Inwards</th>
            <th colSpan={2} scope="colgroup" className="px-2 text-center font-semibold">Outwards</th>
            <th colSpan={2} scope="colgroup" className="px-2 text-center font-semibold">Closing balance</th>
          </tr>
          <tr>
            {['Quantity', 'Value', 'Quantity', 'Value', 'Quantity', 'Value'].map((h, i) => (
              <th key={i} scope="col" className="num px-2 py-1 text-right font-semibold">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr className="border-b border-dashed text-muted-foreground">
            <td className="py-1.5 pr-2 italic">Opening balance</td>
            <td colSpan={4} />
            <td className="num px-2 text-right">{qty(item.opening_qty, unit)}</td>
            <td className="num px-2 text-right">{money(item.opening_value_paise)}</td>
          </tr>
          {item.months.map((m) => (
            <tr key={m.month} className="border-b border-dashed">
              <td className="py-1.5 pr-2">{monthLabel(m.month)}</td>
              <td className="num px-2 text-right">{qty(m.in_qty, unit)}</td>
              <td className="num px-2 text-right">{money(m.in_value_paise)}</td>
              <td className="num px-2 text-right">{qty(m.out_qty, unit)}</td>
              <td className="num px-2 text-right">{money(m.out_value_paise)}</td>
              <td className="num px-2 text-right">{qty(m.closing_qty, unit)}</td>
              <td className="num px-2 text-right">{money(m.closing_value_paise)}</td>
            </tr>
          ))}
          <tr className="border-t-2 font-semibold">
            <td className="py-1.5 pr-2">Grand total</td>
            <td className="num px-2 text-right">{qty(item.in_qty, unit)}</td>
            <td className="num px-2 text-right">{money(item.in_value_paise)}</td>
            <td className="num px-2 text-right">{qty(item.out_qty, unit)}</td>
            <td className="num px-2 text-right">{money(item.out_value_paise)}</td>
            <td className="num px-2 text-right">{qty(item.closing_qty, unit)}</td>
            <td className="num px-2 text-right">{money(item.closing_value_paise)}</td>
          </tr>
        </tbody>
      </table>
    </section>
  )
}
