// Assets: what the client owns that lasts, and what each is worth this year.
//
// An asset is registered from a purchase the books already hold, so the register and the ledger are the same money and a
// purchase of a fixed asset that is not here is an open item. Depreciation is worked out from each asset's terms for the
// year shown; nothing is stored, so changing the year, or an asset's sale date, always gives the right figure.

import { useQuery } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { messageOf } from '@/api/errors'
import { assetSchedule, bills as billsQuery, depreciationStatus, useAssetAction, useBookDepreciation, useRegisterAsset } from '@/api/queries/bills'
import { ledgers as ledgersQuery } from '@/api/queries/books'
import { clientDetail } from '@/api/queries/clients'
import type { Asset } from '@/api/types'
import { Money } from '@/components/ca/Money'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/controls'
import { DateInput } from '@/components/ui/date-input'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { financialYearOf, formatDate, fyLabel, parseDate, parseRupees } from '@/lib/format'
import { useSession } from '@/session/session'

export function AssetsScreen({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const [year, setYear] = useState(() => financialYearOf(new Date()))
  const schedule = useQuery(assetSchedule(clientId, year))
  const action = useAssetAction(clientId)
  const booked = useQuery(depreciationStatus(clientId, year))
  const book = useBookDepreciation(clientId)
  const [adding, setAdding] = useState(false)
  const [selling, setSelling] = useState<Asset | null>(null)
  const mayEdit = can('journal.approve') && !!client.data?.can_post

  if (schedule.isPending) return <Spinner label="Working out the depreciation…" />
  if (schedule.isError) return <ErrorState error={schedule.error} retry={() => void schedule.refetch()} />
  const data = schedule.data

  async function remove(asset: Asset) {
    try {
      await action.mutateAsync({ id: asset.id, action: 'remove' })
      toast.success(`${asset.name} removed from the register`)
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  async function bookYear(remove = false) {
    try {
      await book.mutateAsync({ year, remove })
      toast.success(remove ? 'Depreciation taken out of the books' : `Depreciation for FY ${fyLabel(year)} booked`)
    } catch (e) {
      toast.error(messageOf(e))
    }
  }
  const status = booked.data

  return (
    <div className="grid gap-4">
      {status && status.planned_paise > 0 && (
        <div className="no-print flex flex-wrap items-center justify-between gap-3 rounded-md border p-3 text-sm" role="status">
          <div>
            {status.posted_paise === null ? (
              <>FY {fyLabel(year)}’s depreciation of <strong>{status.planned_display}</strong> is not booked yet. Until it is, the books do not show it.</>
            ) : status.stale ? (
              <span className="text-destructive">
                The register has changed since {status.posted_display} was booked (it now says {status.planned_display}). Take it out and book it again.
              </span>
            ) : (
              <>Booked for FY {fyLabel(year)}: <strong>{status.posted_display}</strong>, as one journal entry dated 31 March.</>
            )}
          </div>
          {mayEdit && (
            <div className="flex gap-2">
              {status.posted_paise === null ? (
                <Button size="sm" onClick={() => void bookYear()} disabled={book.isPending}>Book depreciation</Button>
              ) : (
                <Button size="sm" variant="outline" onClick={() => void bookYear(true)} disabled={book.isPending}>Take it out</Button>
              )}
            </div>
          )}
        </div>
      )}
      <div className="no-print flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Year</span>
          <Select aria-label="Financial year" className="w-36" value={year} onChange={(e) => setYear(Number(e.target.value))}>
            {[0, 1, 2, 3, 4].map((back) => {
              const y = financialYearOf(new Date()) + 1 - back
              return (
                <option key={y} value={y}>
                  FY {fyLabel(y)}
                </option>
              )
            })}
          </Select>
        </label>
        {mayEdit && (
          <Button onClick={() => setAdding(true)}>
            <Plus /> Register an asset
          </Button>
        )}
      </div>

      {data.rows.length === 0 ? (
        <EmptyState title="No assets in use this year">
          Register an asset from a purchase of machinery, a vehicle or equipment. Depreciation is worked out from its terms.
        </EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border bg-card">
          <table className="w-full min-w-[48rem] text-sm">
            <caption className="sr-only">Depreciation for FY {fyLabel(year)}</caption>
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="p-2 text-left font-medium">Asset</th>
                <th scope="col" className="p-2 text-left font-medium">Method</th>
                <th scope="col" className="p-2 text-right font-medium">Days</th>
                <th scope="col" className="p-2 text-right font-medium">Opening (₹)</th>
                <th scope="col" className="p-2 text-right font-medium">Depreciation (₹)</th>
                <th scope="col" className="p-2 text-right font-medium">Closing (₹)</th>
                <th scope="col" className="p-2" />
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.asset.id} className="border-b last:border-0">
                  <th scope="row" className="p-2 text-left font-medium">
                    {r.asset.name}
                    <div className="text-xs font-normal text-muted-foreground">
                      {r.asset.ledger_name} · from {formatDate(r.asset.put_to_use)}
                      {r.asset.disposed_on && <Badge tone="neutral" className="ml-2">Sold {formatDate(r.asset.disposed_on)}</Badge>}
                    </div>
                  </th>
                  <td className="p-2 text-xs">
                    {r.asset.method_display}
                    <div className="text-muted-foreground">
                      {r.asset.method === 'SLM' ? `${r.asset.life_years} years` : `${r.asset.rate_bp / 100}%`}
                    </div>
                  </td>
                  <td className="p-2 text-right tabular-nums">{r.days_in_use}</td>
                  <td className="p-2 text-right"><Money display={r.opening_display} symbol={false} /></td>
                  <td className="p-2 text-right font-medium"><Money display={r.depreciation_display} symbol={false} /></td>
                  <td className="p-2 text-right"><Money display={r.closing_display} symbol={false} /></td>
                  <td className="p-2 text-right">
                    {mayEdit && !r.asset.disposed_on && (
                      <Button variant="ghost" size="sm" onClick={() => setSelling(r.asset)}>Sold</Button>
                    )}
                    {mayEdit && (
                      <Button variant="ghost" size="sm" onClick={() => void remove(r.asset)}>Remove</Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot className="border-t-2 font-semibold">
              <tr>
                <td className="p-2" colSpan={4}>Total</td>
                <td className="p-2 text-right"><Money display={data.total_depreciation_display} symbol={false} /></td>
                <td className="p-2 text-right"><Money display={data.total_closing_display} symbol={false} /></td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      {adding && <RegisterDialog clientId={clientId} onClose={() => setAdding(false)} />}
      {selling && <SellDialog clientId={clientId} asset={selling} onClose={() => setSelling(null)} />}
    </div>
  )
}

function RegisterDialog({ clientId, onClose }: { clientId: string; onClose: () => void }) {
  const ledgers = useQuery(ledgersQuery(clientId))
  const bills = useQuery(billsQuery(clientId, { kind: 'PURCHASE' }))
  const register = useRegisterAsset(clientId)
  const [name, setName] = useState('')
  const [ledger, setLedger] = useState('')
  const [bill, setBill] = useState('')
  const [cost, setCost] = useState('')
  const [residual, setResidual] = useState('')
  const [used, setUsed] = useState('')
  const [method, setMethod] = useState('SLM')
  const [life, setLife] = useState('10')
  const [rate, setRate] = useState('15')
  const [error, setError] = useState<string | null>(null)

  const assetLedgers = (ledgers.data ?? []).filter((l) => l.group === 'FIXED_ASSET' && l.is_active)

  function submit() {
    const costPaise = parseRupees(cost)
    const residualPaise = residual.trim() ? parseRupees(residual) : 0
    const date = parseDate(used)
    if (!name.trim()) return setError('Give the asset a name.')
    if (!ledger) return setError('Choose the fixed-asset ledger.')
    if (!costPaise || costPaise <= 0) return setError('Enter the cost in rupees, like 10,00,000.00.')
    if (residualPaise === null) return setError('The residual value is not an amount.')
    if (!date) return setError('Enter the date it was put to use as DD-MM-YYYY.')
    setError(null)
    register.mutate(
      {
        name: name.trim(),
        ledger,
        bill: bill || null,
        cost_paise: costPaise,
        residual_paise: residualPaise,
        put_to_use: date,
        method,
        life_years: method === 'SLM' ? Number(life) || 0 : 0,
        rate_bp: method === 'SLM' ? 0 : Math.round((Number(rate) || 0) * 100),
      },
      { onSuccess: () => { toast.success('Asset registered'); onClose() }, onError: (e) => setError(messageOf(e)) },
    )
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[92svh] overflow-y-auto sm:max-w-xl" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Register an asset</DialogTitle>
          <DialogDescription>Pick the purchase it was bought on: its cost cannot exceed what that purchase put on the ledger.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <Field label="Name">{(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Fixed-asset ledger">
              {(p) => (
                <Select {...p} value={ledger} onChange={(e) => setLedger(e.target.value)}>
                  <option value="">Choose…</option>
                  {assetLedgers.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                </Select>
              )}
            </Field>
            <Field label="Purchase">
              {(p) => (
                <Select {...p} value={bill} onChange={(e) => setBill(e.target.value)}>
                  <option value="">Not from a purchase</option>
                  {(bills.data ?? []).map((b) => (
                    <option key={b.id} value={b.id}>{b.party_name} · {b.reference} · {b.total_display}</option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Cost (₹)">{(p) => <Input {...p} inputMode="decimal" className="text-right" value={cost} onChange={(e) => setCost(e.target.value)} />}</Field>
            <Field label="Residual value (₹)">{(p) => <Input {...p} inputMode="decimal" className="text-right" value={residual} onChange={(e) => setResidual(e.target.value)} />}</Field>
            <Field label="Put to use on">{(p) => <DateInput {...p} value={used} onChange={(e) => setUsed(e.target.value)} />}</Field>
            <Field label="Depreciation method">
              {(p) => (
                <Select {...p} value={method} onChange={(e) => setMethod(e.target.value)}>
                  <option value="SLM">Straight line (Companies Act)</option>
                  <option value="WDV">Written-down value, by days (Companies Act)</option>
                  <option value="WDV_IT">Written-down value, 180-day rule (Income-tax)</option>
                </Select>
              )}
            </Field>
            {method === 'SLM' ? (
              <Field label="Useful life (years)">{(p) => <Input {...p} inputMode="numeric" className="text-right" value={life} onChange={(e) => setLife(e.target.value)} />}</Field>
            ) : (
              <Field label="Rate (% a year)">{(p) => <Input {...p} inputMode="decimal" className="text-right" value={rate} onChange={(e) => setRate(e.target.value)} />}</Field>
            )}
          </div>
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <div className="flex justify-end">
            <Button onClick={submit} disabled={register.isPending}>{register.isPending ? 'Saving…' : 'Register'}</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function SellDialog({ clientId, asset, onClose }: { clientId: string; asset: Asset; onClose: () => void }) {
  const action = useAssetAction(clientId)
  const [on, setOn] = useState('')
  const [price, setPrice] = useState('')
  const [error, setError] = useState<string | null>(null)

  function submit() {
    const date = parseDate(on)
    const paise = price.trim() ? parseRupees(price) : 0
    if (!date) return setError('Enter the date of sale as DD-MM-YYYY.')
    if (paise === null) return setError('The sale price is not an amount.')
    setError(null)
    action.mutate(
      { id: asset.id, action: 'dispose', body: { disposed_on: date, proceeds_paise: paise } },
      { onSuccess: () => { toast.success('Sale recorded'); onClose() }, onError: (e) => setError(messageOf(e)) },
    )
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{asset.name}: sold</DialogTitle>
          <DialogDescription>Depreciation stops on the day of sale. Book the sale itself as an ordinary entry.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <Field label="Sold on">{(p) => <DateInput {...p} value={on} onChange={(e) => setOn(e.target.value)} />}</Field>
          <Field label="Sale price (₹)">{(p) => <Input {...p} inputMode="decimal" className="text-right" value={price} onChange={(e) => setPrice(e.target.value)} />}</Field>
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <div className="flex justify-end">
            <Button onClick={submit} disabled={action.isPending}>Record the sale</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
