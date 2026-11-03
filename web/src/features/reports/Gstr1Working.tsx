// The GSTR-1 working for one month: the tables a return is filled from, taken from the booked sales invoices and credit notes.

import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { useState } from 'react'
import { defaultReturnMonth } from '@/lib/returnMonth'
import { gstr1, gstr1File, type Gstr1Row } from '@/api/queries/books'
import { messageOf } from '@/api/errors'
import { Button } from '@/components/ui/button'
import { formatDate, formatPaise } from '@/lib/format'
import { saveFile } from '@/platform/download'
import { toast } from '@/lib/toast'

const money = (paise: number) => (paise === 0 ? '–' : formatPaise(paise, { symbol: false }))

function Invoices({ title, rows }: { title: string; rows: Gstr1Row[] }) {
  if (rows.length === 0) return null
  return (
    <div className="grid gap-1">
      <h4 className="font-medium">{title}</h4>
      <table className="w-full" aria-label={title}>
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="py-1 font-medium">Number</th>
            <th className="py-1 font-medium">Date</th>
            <th className="py-1 font-medium">Party</th>
            <th className="py-1 font-medium">GSTIN</th>
            <th className="py-1 text-right font-medium">Value</th>
            <th className="py-1 text-right font-medium">Rate %</th>
            <th className="py-1 text-right font-medium">Taxable</th>
            <th className="py-1 text-right font-medium">IGST</th>
            <th className="py-1 text-right font-medium">CGST</th>
            <th className="py-1 text-right font-medium">SGST</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.number}-${r.date}`} className="border-t border-border-strong">
              <td className="py-1">{r.number}</td>
              <td className="py-1">{formatDate(r.date)}</td>
              <td className="py-1">{r.party}</td>
              <td className="py-1">{r.gstin}</td>
              <td className="py-1 text-right tabular-nums">{money(r.value_paise)}</td>
              <td className="py-1 text-right tabular-nums">{r.rate}</td>
              <td className="py-1 text-right tabular-nums">{money(r.taxable_paise)}</td>
              <td className="py-1 text-right tabular-nums">{money(r.igst_paise)}</td>
              <td className="py-1 text-right tabular-nums">{money(r.cgst_paise)}</td>
              <td className="py-1 text-right tabular-nums">{money(r.sgst_paise)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Gstr1Working({ clientId, fy }: { clientId: string; fy: number }) {
  const [month, setMonth] = useState(() => defaultReturnMonth(fy))
  const query = useQuery(gstr1(clientId, month))
  const months = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3].map((m) => `${m >= 4 ? fy : fy + 1}-${String(m).padStart(2, '0')}`)
  const file = useQuery(gstr1File(clientId, month))
  const [missing, setMissing] = useState<string[] | null>(null)
  async function download() {
    const got = await file.refetch()
    if (got.error || !got.data) return void toast.error(messageOf(got.error))
    setMissing(got.data.missing)
    await saveFile(`gstr1-${month}.json`, new Blob([JSON.stringify(got.data.json, null, 2)], { type: 'application/json' }))
  }
  const d = query.data
  const empty = d && d.b2b.rows.length + d.b2cl.rows.length + d.b2cs.rows.length + d.credit_notes_registered.rows.length + d.credit_notes_unregistered.rows.length === 0

  return (
    <section aria-label="GSTR-1 working" className="grid gap-3 text-sm">
      <div className="flex items-center gap-2">
        <h3 className="font-medium">GSTR-1 working</h3>
        <label htmlFor="gstr1-month" className="text-muted-foreground">
          GSTR-1 month
        </label>
        <select id="gstr1-month" className="h-9 rounded-md border border-border-strong bg-transparent px-2" value={month} onChange={(e) => setMonth(e.target.value)}>
          {months.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>
      {d && empty && <p className="text-muted-foreground">No taxed sales or credit notes in this month.</p>}
      {d && !empty && (
        <>
          <p className="flex items-center gap-2">
            {d.agrees_with_3b ? <CheckCircle2 className="size-4 shrink-0" aria-hidden /> : <AlertTriangle className="size-4 shrink-0" aria-hidden />}
            {d.agrees_with_3b
              ? 'The taxable value in these tables is the outward supplies on the GSTR-3B working.'
              : `The tables total ${formatPaise(d.taxable_in_tables_paise)} taxable; the GSTR-3B working has ${formatPaise(d.taxable_in_3b_paise)}.`}
          </p>
          <Invoices title="4 · B2B invoices (to registered parties)" rows={d.b2b.rows} />
          <Invoices title="5 · B2C large (inter-state, over ₹2,50,000)" rows={d.b2cl.rows} />
          {d.b2cs.rows.length > 0 && (
            <div className="grid gap-1">
              <h4 className="font-medium">7 · B2C other, by rate</h4>
              <table className="w-full" aria-label="B2C other">
                <thead>
                  <tr className="text-left text-xs text-muted-foreground">
                    <th className="py-1 font-medium">Supply</th>
                    <th className="py-1 text-right font-medium">Rate %</th>
                    <th className="py-1 text-right font-medium">Taxable</th>
                    <th className="py-1 text-right font-medium">IGST</th>
                    <th className="py-1 text-right font-medium">CGST</th>
                    <th className="py-1 text-right font-medium">SGST</th>
                  </tr>
                </thead>
                <tbody>
                  {d.b2cs.rows.map((r) => (
                    <tr key={`${r.supply}-${r.rate}`} className="border-t border-border-strong">
                      <td className="py-1">{r.supply}</td>
                      <td className="py-1 text-right tabular-nums">{r.rate}</td>
                      <td className="py-1 text-right tabular-nums">{money(r.taxable_paise)}</td>
                      <td className="py-1 text-right tabular-nums">{money(r.igst_paise)}</td>
                      <td className="py-1 text-right tabular-nums">{money(r.cgst_paise)}</td>
                      <td className="py-1 text-right tabular-nums">{money(r.sgst_paise)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Invoices title="9B · Credit notes to registered parties" rows={d.credit_notes_registered.rows} />
          <Invoices title="9B · Credit notes to unregistered parties" rows={d.credit_notes_unregistered.rows} />
        </>
      )}
      {d && (
        <>
          <p>
            <strong>8 · Nil-rated, exempt and non-GST:</strong> zero-rated {money(d.exempt_nil_non_gst.zero_rated_paise)}, nil and exempt {money(d.exempt_nil_non_gst.exempt_paise)},
            non-GST {money(d.exempt_nil_non_gst.non_gst_paise)} (entered on the GSTR-3B working); sales booked with no tax {money(d.exempt_nil_non_gst.untaxed_sales_paise)}.
          </p>
          {d.hsn.length > 0 && (
            <div className="grid gap-1">
              <h4 className="font-medium">12 · HSN summary</h4>
              <table className="w-full" aria-label="HSN summary">
                <thead>
                  <tr className="text-left text-xs text-muted-foreground">
                    <th className="py-1 font-medium">HSN</th>
                    <th className="py-1 font-medium">Unit</th>
                    <th className="py-1 text-right font-medium">Quantity</th>
                    <th className="py-1 text-right font-medium">Taxable</th>
                    <th className="py-1 text-right font-medium">IGST</th>
                    <th className="py-1 text-right font-medium">CGST</th>
                    <th className="py-1 text-right font-medium">SGST</th>
                  </tr>
                </thead>
                <tbody>
                  {d.hsn.map((r) => (
                    <tr key={`${r.hsn}-${r.unit}`} className="border-t border-border-strong">
                      <td className="py-1">{r.hsn}</td>
                      <td className="py-1">{r.unit}</td>
                      <td className="py-1 text-right tabular-nums">{r.quantity}</td>
                      <td className="py-1 text-right tabular-nums">{money(r.taxable_paise)}</td>
                      <td className="py-1 text-right tabular-nums">{money(r.igst_paise)}</td>
                      <td className="py-1 text-right tabular-nums">{money(r.cgst_paise)}</td>
                      <td className="py-1 text-right tabular-nums">{money(r.sgst_paise)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {d.hsn_bills_without_items > 0 && (
            <p className="text-muted-foreground">
              {d.hsn_bills_without_items} invoice(s) have no item lines, so the HSN summary leaves them out. Upload the invoice or key its items.
            </p>
          )}
          {d.documents.length > 0 && (
            <p>
              <strong>13 · Documents issued:</strong> {d.documents.map((x) => `${x.label}: ${x.from} to ${x.to} (${x.count})`).join('; ')}.
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" variant="outline" loading={file.isFetching} onClick={() => void download()}>
              Download GSTR-1 JSON
            </Button>
            <span className="text-xs text-muted-foreground">For the GST offline tool; check it there before filing.</span>
          </div>
          {missing && missing.length > 0 && (
            <ul className="list-disc pl-5 text-xs" aria-label="Missing from the GSTR-1 file">
              {missing.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          )}
          <p className="text-xs text-muted-foreground">
            Place of supply is not recorded, so B2C is by rate and inter/intra-state, not by state. Exports, SEZ and e-commerce supplies are not told apart from other sales.
          </p>
        </>
      )}
    </section>
  )
}
