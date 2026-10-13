// Assets: what the client owns that lasts, and what each is worth this year.
//
// An asset is registered from a purchase the books already hold, so the register and the ledger are the same money and a
// purchase of a fixed asset that is not here is an open item. Depreciation is worked out from each asset's terms for the
// year shown; nothing is stored, so changing the year, or an asset's sale date, always gives the right figure.

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from '@/lib/toast'
import { messageOf } from '@/api/errors'
import { assetSchedule, bills as billsQuery, depreciationStatus, useAssetAction, useBookDepreciation, useRegisterAsset } from '@/api/queries/bills'
import { ledgers as ledgersQuery } from '@/api/queries/books'
import { clientDetail } from '@/api/queries/clients'
import type { Asset } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
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
import { useFy } from '@/features/shell/useFy'
import { financialYearOf, formatDate, fyLabel, parseDate, parseRupees } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'

export function AssetsScreen({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  // The year starts at the one chosen in the top bar and follows it; the picker below can still look at another one.
  const { fy } = useFy()
  const [year, setYear] = useState(fy)
  useEffect(() => setYear(fy), [fy])
  const schedule = useQuery({ ...assetSchedule(clientId, year), placeholderData: keepPreviousData })
  const action = useAssetAction(clientId)
  const booked = useQuery({ ...depreciationStatus(clientId, year), placeholderData: keepPreviousData })
  const book = useBookDepreciation(clientId)
  const [adding, setAdding] = useState(false)
  const [selling, setSelling] = useState<Asset | null>(null)
  const [removing, setRemoving] = useState<Asset | null>(null)
  // Remounts (and so fades in) only when another year has really arrived, not while the old one is held, dimmed, in its place.
  const arrived = useRef(0)
  if (schedule.data && !schedule.isPlaceholderData) arrived.current = schedule.dataUpdatedAt
  const changing = schedule.isPlaceholderData
  const mayEdit = can('journal.approve') && !!client.data?.can_post

  if (schedule.isPending) return <Spinner label="Working out the depreciation…" />
  if (schedule.isError) return <ErrorState error={schedule.error} retry={() => void schedule.refetch()} />
  const data = schedule.data

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
        <div
          key={status.posted_paise === null ? 'open' : status.stale ? 'stale' : 'booked'}
          className="no-print fade-in flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border-strong bg-card p-4 text-sm"
          role="status"
        >
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
                <Button size="sm" onClick={() => void bookYear()} loading={book.isPending}>Book depreciation</Button>
              ) : (
                <Button size="sm" variant="outline" onClick={() => void bookYear(true)} loading={book.isPending}>Take it out</Button>
              )}
            </div>
          )}
        </div>
      )}
      <div className="no-print flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Year</span>
          <Select aria-label="Year shown" className="w-36" value={year} onChange={(e) => setYear(Number(e.target.value))}>
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
        <div
          key={arrived.current}
          aria-busy={changing || undefined}
          className={cn('fade-in overflow-x-auto rounded-xl border border-border-strong bg-card transition-opacity duration-200', changing && 'opacity-50')}
        >
          <table className="w-full min-w-[48rem] text-sm">
            <caption className="sr-only">Depreciation for FY {fyLabel(year)}</caption>
            <thead className="border-b border-border-strong text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-4 py-4 text-left font-semibold">Asset</th>
                <th scope="col" className="px-4 py-4 text-left font-semibold">Method</th>
                <th scope="col" className="px-4 py-4 text-right font-semibold">Days</th>
                <th scope="col" className="px-4 py-4 text-right font-semibold">Opening (₹)</th>
                <th scope="col" className="px-4 py-4 text-right font-semibold">Depreciation (₹)</th>
                <th scope="col" className="px-4 py-4 text-right font-semibold">Closing (₹)</th>
                <th scope="col" className="px-4 py-4" />
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r, i) => (
                <tr
                  key={r.asset.id}
                  className="fade-in border-b border-border-strong transition-colors last:border-0 hover:bg-hover"
                  style={{ animationDelay: `${Math.min(i, 10) * 40}ms` }}
                >
                  <th scope="row" className="px-4 py-4 text-left font-medium text-heading">
                    {r.asset.name}
                    <div className="mt-0.5 text-xs font-normal text-muted-foreground">
                      {r.asset.ledger_name} · from {formatDate(r.asset.put_to_use)}
                      {r.asset.disposed_on && <Badge tone="neutral" className="ml-2">Sold {formatDate(r.asset.disposed_on)}</Badge>}
                    </div>
                  </th>
                  <td className="px-4 py-4 text-xs">
                    {r.asset.method_display}
                    <div className="mt-0.5 text-muted-foreground">
                      {r.asset.method === 'SLM' ? `${r.asset.life_years} years` : `${r.asset.rate_bp / 100}%`}
                    </div>
                  </td>
                  <td className="px-4 py-4 text-right tabular-nums">{r.days_in_use}</td>
                  <td className="px-4 py-4 text-right"><Money display={r.opening_display} symbol={false} /></td>
                  <td className="px-4 py-4 text-right font-medium"><Money display={r.depreciation_display} symbol={false} /></td>
                  <td className="px-4 py-4 text-right"><Money display={r.closing_display} symbol={false} /></td>
                  <td className="whitespace-nowrap px-4 py-3 text-right">
                    {mayEdit && !r.asset.disposed_on && (
                      <Button variant="ghost" size="sm" onClick={() => setSelling(r.asset)}>Sold</Button>
                    )}
                    {mayEdit && (
                      <Button variant="ghost" size="sm" className="text-destructive" onClick={() => setRemoving(r.asset)}>Remove</Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot className="border-t-2 border-foreground bg-surface-2 font-semibold">
              <tr>
                <td className="px-4 py-4" colSpan={4}>Total</td>
                <td className="px-4 py-4 text-right"><Money display={data.total_depreciation_display} symbol={false} /></td>
                <td className="px-4 py-4 text-right"><Money display={data.total_closing_display} symbol={false} /></td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      <Confirm
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={`Remove ${removing?.name ?? 'this asset'} from the register?`}
        confirmLabel="Remove"
        destructive
        onConfirm={async () => {
          if (!removing) return
          await action.mutateAsync({ id: removing.id, action: 'remove' })
          toast.success(`${removing.name} removed from the register`)
        }}
      >
        <p>The asset is deleted from the register and its depreciation goes with it. If a year's depreciation was already booked, take it out and book it again. The purchase it came from is not touched.</p>
      </Confirm>

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
    <Dialog open onOpenChange={(open) => !open && !register.isPending && onClose()}>
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
            <Button onClick={submit} loading={register.isPending}>{register.isPending ? 'Saving…' : 'Register'}</Button>
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
    <Dialog open onOpenChange={(open) => !open && !action.isPending && onClose()}>
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
            <Button onClick={submit} loading={action.isPending}>Record the sale</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
