// What the financial statements need that no ledger holds: the entity's description and policies (Notes 1 and 2), the units
// the figures are rounded to, the year's closing stock, and the partners with their shares and movements (Note 3).

import { useQuery } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { statementSettings } from '@/api/queries/books'
import { useInvalidateClient, V1 } from '@/api/queries/clients'
import type { StatementSettings } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Select, Textarea } from '@/components/ui/controls'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { fyLabel, parseRupees } from '@/lib/format'

const ROUNDING: [string, string][] = [
  ['rupees', 'Rupees (to the paisa)'],
  ['hundreds', 'Hundreds'],
  ['thousands', 'Thousands'],
  ['lakhs', 'Lakhs'],
  ['crores', 'Crores'],
]

interface PartnerDraft {
  name: string
  share: string
  opening: string
  introduced: string
  remuneration: string
  interest: string
  withdrawals: string
}

const rupees = (paise: number | null | undefined) => (paise === null || paise === undefined ? '' : (paise / 100).toFixed(2))
const blank = (): PartnerDraft => ({ name: '', share: '', opening: '', introduced: '', remuneration: '', interest: '', withdrawals: '' })

/** Rupees typed -> paise: empty is `empty`, anything that is not an amount is undefined. */
function paise(text: string, empty: number | null): number | null | undefined {
  if (!text.trim()) return empty
  const p = parseRupees(text)
  return p === null || p < 0 ? undefined : p
}

export function StatementDetails({ clientId, fy, onClose }: { clientId: string; fy: number; onClose: () => void }) {
  const settings = useQuery(statementSettings(clientId))
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent aria-describedby={undefined} className="max-h-[90vh] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Details for the financial statements · FY {fyLabel(fy)}</DialogTitle>
          <DialogDescription>
            What the ledgers cannot tell: Notes 1 and 2, the closing stock, and the partners for Note 3. The ledgers stay as they are.
          </DialogDescription>
        </DialogHeader>
        {settings.isPending ? <Spinner label="Loading…" /> : settings.error ? <p className="text-sm text-destructive">{messageOf(settings.error)}</p> : <Form clientId={clientId} fy={fy} onClose={onClose} initial={settings.data} />}
      </DialogContent>
    </Dialog>
  )
}

function Form({ clientId, fy, onClose, initial }: { clientId: string; fy: number; onClose: () => void; initial: StatementSettings }) {
  const invalidate = useInvalidateClient(clientId)
  const year = initial.years?.[String(fy)]
  const before = initial.years?.[String(fy - 1)]
  const draft = (p: NonNullable<typeof year>['partners']): PartnerDraft[] =>
    (p ?? []).map((x) => ({
      name: x.name,
      share: String((x.share_bp ?? 0) / 100),
      opening: rupees(x.opening_paise),
      introduced: rupees(x.introduced_paise),
      remuneration: rupees(x.remuneration_paise),
      interest: rupees(x.interest_paise),
      withdrawals: rupees(x.withdrawals_paise),
    }))

  const [about, setAbout] = useState(initial.about ?? '')
  const [policies, setPolicies] = useState(initial.policies ?? '')
  const [rounding, setRounding] = useState<string>(initial.rounding ?? 'rupees')
  const [stock, setStock] = useState(rupees(year?.closing_stock_paise))
  const [partners, setPartners] = useState<PartnerDraft[]>(draft(year?.partners))
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const set = (i: number, key: keyof PartnerDraft, value: string) => setPartners((rows) => rows.map((r, j) => (j === i ? { ...r, [key]: value } : r)))

  async function save() {
    setError(null)
    const closing = paise(stock, null)
    if (closing === undefined) return setError('The closing stock is not an amount.')
    const rows = []
    for (const [i, r] of partners.entries()) {
      if (!r.name.trim()) continue
      const share = Number(r.share || 0)
      const amounts = [paise(r.opening, null), paise(r.introduced, 0), paise(r.remuneration, 0), paise(r.interest, 0), paise(r.withdrawals, 0)]
      if (!Number.isFinite(share) || share < 0 || share > 100 || amounts.includes(undefined)) return setError(`Row ${i + 1}: check the share and the amounts.`)
      rows.push({
        name: r.name.trim(),
        share_bp: Math.round(share * 100),
        opening_paise: amounts[0],
        introduced_paise: amounts[1],
        remuneration_paise: amounts[2],
        interest_paise: amounts[3],
        withdrawals_paise: amounts[4],
      })
    }
    if (rows.reduce((sum, r) => sum + r.share_bp, 0) > 10_000) return setError('The partners’ shares add up to more than 100%.')
    setBusy(true)
    try {
      await raw.put(`${V1}/clients/${clientId}/reports/financial-statements/settings/`, {
        about,
        policies,
        rounding,
        years: { [String(fy)]: { closing_stock_paise: closing, partners: rows } },
      })
      await invalidate()
      toast.success('Saved; the statements are updated')
      onClose()
    } catch (e) {
      setError(messageOf(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Note 1 · Brief about the entity" hint="Nature of business, constitution, place.">
          {(p) => <Textarea {...p} rows={4} maxLength={8000} value={about} onChange={(e) => setAbout(e.target.value)} />}
        </Field>
        <Field label="Note 2 · Significant accounting policies" hint="Basis of accounting, revenue, depreciation, inventories.">
          {(p) => <Textarea {...p} rows={4} maxLength={8000} value={policies} onChange={(e) => setPolicies(e.target.value)} />}
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Figures in" hint="The statements, notes and the Excel file are rounded to this.">
          {(p) => (
            <Select {...p} value={rounding} onChange={(e) => setRounding(e.target.value)}>
              {ROUNDING.map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </Select>
          )}
        </Field>
        <Field label={`Closing stock at 31 March ${fy + 1} (₹)`} hint="Leave empty if the stock ledgers already carry it. Entered here, it lowers the cost of goods sold and is shown under Inventories.">
          {(p) => <Input {...p} inputMode="decimal" value={stock} onChange={(e) => setStock(e.target.value)} />}
        </Field>
      </div>

      <section aria-label="Partners" className="grid gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-heading">Note 3 · Partners / proprietor</h3>
          <div className="flex gap-2">
            {before?.partners?.length ? (
              <Button type="button" size="sm" variant="outline" onClick={() => setPartners(draft(before.partners).map((r) => ({ ...r, opening: '', introduced: '', remuneration: '', interest: '', withdrawals: '' })))}>
                Start from last year’s partners
              </Button>
            ) : null}
            <Button type="button" size="sm" variant="outline" onClick={() => setPartners((rows) => [...rows, blank()])}>
              <Plus /> Add a partner
            </Button>
          </div>
        </div>
        {partners.length === 0 ? (
          <p className="text-sm text-muted-foreground">None yet. Add each partner (or the proprietor) to get the capital table. Remuneration and interest are what was credited to the partner; the share of profit is worked out from the share.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[56rem] text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  {['Name', 'Share %', 'Opening (₹)', 'Introduced', 'Remuneration', 'Interest', 'Withdrawals', ''].map((h) => (
                    <th key={h} scope="col" className="px-1 py-1 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {partners.map((r, i) => (
                  <tr key={i}>
                    <td className="p-1"><Input aria-label={`Partner ${i + 1} name`} value={r.name} onChange={(e) => set(i, 'name', e.target.value)} /></td>
                    <td className="w-20 p-1"><Input aria-label={`Partner ${i + 1} share`} inputMode="decimal" value={r.share} onChange={(e) => set(i, 'share', e.target.value)} /></td>
                    {(['opening', 'introduced', 'remuneration', 'interest', 'withdrawals'] as const).map((k) => (
                      <td key={k} className="p-1">
                        <Input aria-label={`Partner ${i + 1} ${k}`} inputMode="decimal" placeholder={k === 'opening' ? 'carried' : ''} value={r[k]} onChange={(e) => set(i, k, e.target.value)} />
                      </td>
                    ))}
                    <td className="p-1">
                      <Button type="button" size="icon" variant="ghost" aria-label={`Remove partner ${i + 1}`} onClick={() => setPartners((rows) => rows.filter((_, j) => j !== i))}>
                        <Trash2 />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button onClick={() => void save()} disabled={busy}>Save</Button>
      </DialogFooter>
    </div>
  )
}
