// The GSTR-3B working for one month: the tables a return is filled from. The invoices give most of it; what they cannot hold (exempt,
// nil-rated and zero-rated supplies, credit reversed, interest, late fee, an opening credit to put right) is entered here for the month.

import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { toast } from '@/lib/toast'
import { messageOf } from '@/api/errors'
import { gstr3b, useSaveGstr3bEntries, type Gstr3bTax } from '@/api/queries/books'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { formatPaise, parseRupees } from '@/lib/format'
import { useSession } from '@/session/session'

const money = (paise: number) => (paise === 0 ? '–' : formatPaise(paise, { symbol: false }))
const HEADS = ['igst', 'cgst', 'sgst', 'cess'] as const
const HEAD_LABEL = { igst: 'IGST', cgst: 'CGST', sgst: 'SGST', cess: 'Cess' } as const
const NO_TAX: Gstr3bTax = { igst_paise: 0, cgst_paise: 0, sgst_paise: 0, cess_paise: 0 }

function TaxRow({ label, row, taxable }: { label: string; row: Gstr3bTax; taxable?: number }) {
  return (
    <tr className="border-t border-border-strong">
      <td className="py-1">{label}</td>
      <td className="py-1 text-right tabular-nums">{taxable === undefined ? '' : money(taxable)}</td>
      {HEADS.map((h) => (
        <td key={h} className="py-1 text-right tabular-nums">
          {money(row[`${h}_paise`])}
        </td>
      ))}
    </tr>
  )
}

const SINGLE: { key: string; label: string }[] = [
  { key: 'zero_rated_paise', label: 'Zero-rated supplies (3.1(b))' },
  { key: 'exempt_paise', label: 'Nil-rated and exempt supplies (3.1(c))' },
  { key: 'non_gst_paise', label: 'Non-GST outward supplies (3.1(e))' },
  { key: 'inward_exempt_paise', label: 'Inward exempt, nil-rated and non-GST (5)' },
  { key: 'late_fee_paise', label: 'Late fee (5.1)' },
]
const PER_HEAD: { prefix: string; label: string }[] = [
  { prefix: 'itc_reversed', label: 'ITC reversed (4(B))' },
  { prefix: 'interest', label: 'Interest (5.1)' },
  { prefix: 'opening_credit', label: 'Opening credit, if the carried figure is wrong' },
]

function EntriesForm({ clientId, month, entries }: { clientId: string; month: string; entries: Record<string, number | null> }) {
  const save = useSaveGstr3bEntries(clientId, month)
  const [text, setText] = useState<Record<string, string>>({})
  useEffect(() => {
    setText(Object.fromEntries(Object.entries(entries).map(([k, v]) => [k, v ? String(v / 100) : ''])))
  }, [entries])

  function submit() {
    const body: Record<string, number | null> = {}
    for (const [key, value] of Object.entries(text)) {
      const paise = value.trim() ? parseRupees(value) : null
      if (value.trim() && paise === null) return void toast.error('Amounts are in rupees, like 1500 or 1500.50.')
      body[key] = key.startsWith('opening_credit') ? paise : (paise ?? 0)
    }
    save.mutate(body, { onSuccess: () => toast.success('Saved'), onError: (e) => toast.error(messageOf(e)) })
  }

  const box = (key: string, label: string) => (
    <label key={key} className="grid gap-0.5 text-xs text-muted-foreground">
      <span aria-hidden>{label}</span>
      <Input aria-label={label} inputMode="decimal" className="w-32" value={text[key] ?? ''} onChange={(e) => setText({ ...text, [key]: e.target.value })} />
    </label>
  )

  return (
    <div className="grid gap-3 rounded-md border border-line p-3">
      <h4 className="font-medium">Enter for this month what the invoices do not hold</h4>
      <div className="flex flex-wrap items-end gap-2">{SINGLE.map((s) => box(s.key, s.label))}</div>
      {PER_HEAD.map((g) => (
        <div key={g.prefix} className="flex flex-wrap items-end gap-2">
          {HEADS.map((h) => box(`${g.prefix}_${h}_paise`, `${g.label}: ${HEAD_LABEL[h]}`))}
        </div>
      ))}
      <div>
        <Button loading={save.isPending} onClick={submit}>
          Save for this month
        </Button>
      </div>
    </div>
  )
}

export function Gstr3bWorking({ clientId, fy }: { clientId: string; fy: number }) {
  const { can } = useSession()
  const [month, setMonth] = useState(`${fy}-04`)
  const query = useQuery(gstr3b(clientId, month))
  const months = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3].map((m) => `${m >= 4 ? fy : fy + 1}-${String(m).padStart(2, '0')}`)
  const d = query.data

  return (
    <section aria-label="GSTR-3B working" className="grid gap-3 text-sm">
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
          {d.untaxed_unexplained_paise > 0 && (
            <p role="status" className="rounded-md border border-accent-edge bg-accent p-2">
              {formatPaise(d.untaxed_unexplained_paise)} of this month&apos;s sales carry no tax. Enter them below as zero-rated, nil-rated or exempt so the return
              accounts for them.
            </p>
          )}
          <table className="w-full" aria-label="GSTR-3B tables">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="py-1 font-medium">Table</th>
                <th className="py-1 text-right font-medium">Taxable value</th>
                {HEADS.map((h) => (
                  <th key={h} className="py-1 text-right font-medium">
                    {HEAD_LABEL[h]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <TaxRow label="3.1(a) Outward taxable supplies" row={d.outward_taxable} taxable={d.outward_taxable.taxable_paise} />
              <TaxRow label="3.1(b) Zero-rated supplies" row={NO_TAX} taxable={d.zero_rated_paise} />
              <TaxRow label="3.1(c) Nil-rated and exempt" row={NO_TAX} taxable={d.exempt_nil_paise} />
              <TaxRow label="3.1(d) Inward supplies on reverse charge" row={d.inward_reverse_charge} taxable={d.inward_reverse_charge.taxable_paise} />
              <TaxRow label="3.1(e) Non-GST outward supplies" row={NO_TAX} taxable={d.non_gst_outward_paise} />
              <TaxRow label="4(A)(3) ITC: reverse charge" row={d.itc_reverse_charge} />
              <TaxRow label="4(A)(5) ITC: all other" row={d.itc_all_other} />
              <TaxRow label="Credit brought forward" row={d.opening_credit} />
              <TaxRow label="4(B) ITC reversed" row={d.itc_reversed} />
              <TaxRow label="6.1 Tax on outward supplies" row={d.liability} />
              <TaxRow label="6.1 Paid through credit" row={d.paid_by_credit} />
              <TaxRow label="6.1 Paid in cash (reverse charge, interest and any balance)" row={d.paid_in_cash} />
              <TaxRow label="5.1 Interest" row={d.interest} />
              <TaxRow label="Credit carried forward" row={d.carry_forward} />
            </tbody>
          </table>
          <p className="text-xs text-muted-foreground">
            From {d.counts.sales} sales, {d.counts.purchases} purchases and {d.counts.reverse_charge} reverse-charge purchases. Late fee {money(d.late_fee_paise)}; inward exempt
            supplies {money(d.inward_exempt_paise)}. Credit is carried from April and used as the law orders: IGST credit against IGST, CGST, then SGST; CGST or SGST credit against
            its own tax, then IGST. Reverse-charge tax, interest and late fee are paid in cash.
          </p>
          {can('ledger.manage') && <EntriesForm clientId={clientId} month={month} entries={d.entries} />}
        </>
      )}
    </section>
  )
}
