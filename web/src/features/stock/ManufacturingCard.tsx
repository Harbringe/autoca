// Making finished goods from components: define what a finished item is made of, see what a run would take and cost, and run it.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { messageOf } from '@/api/errors'
import { godowns } from '@/api/queries/godowns'
import { boms, runPlan, useMakeBom, useProduce, useRemoveBom, type Bom, type BomComponent } from '@/api/queries/manufacturing'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { formatPaise, parseRupees } from '@/lib/format'
import { toast } from '@/lib/toast'

const money = (paise: number) => formatPaise(paise, { symbol: false })
const today = () => new Date().toISOString().slice(0, 10)
const EMPTY: BomComponent = { name: '', unit: '', quantity: '' }

function NewBom({ clientId }: { clientId: string }) {
  const make = useMakeBom(clientId)
  const [name, setName] = useState('')
  const [unit, setUnit] = useState('')
  const [output, setOutput] = useState('1')
  const [rows, setRows] = useState<BomComponent[]>([{ ...EMPTY }])
  const set = (i: number, patch: Partial<BomComponent>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))

  function submit() {
    const components = rows.filter((r) => r.name.trim() || r.quantity.trim())
    make.mutate(
      { name: name.trim(), unit: unit.trim(), output_quantity: output, components: components.map((c) => ({ ...c, name: c.name.trim() })) },
      { onSuccess: () => { setName(''); setUnit(''); setOutput('1'); setRows([{ ...EMPTY }]); toast.success('Bill of materials saved') }, onError: (e) => toast.error(messageOf(e)) },
    )
  }

  return (
    <div className="mt-2 grid gap-2 border-t border-border-strong pt-3" role="group" aria-label="New bill of materials">
      <h3 className="text-sm font-medium">New bill of materials</h3>
      <div className="flex flex-wrap items-end gap-2">
        <Input aria-label="Finished item" className="w-56" placeholder="Finished item" value={name} onChange={(e) => setName(e.target.value)} />
        <Input aria-label="Finished unit" className="w-20" placeholder="Unit" value={unit} onChange={(e) => setUnit(e.target.value)} />
        <label className="flex items-center gap-1 text-xs text-muted-foreground">
          made from these, per
          <Input aria-label="Batch size" inputMode="decimal" className="w-20" value={output} onChange={(e) => setOutput(e.target.value)} />
        </label>
      </div>
      {rows.map((r, i) => (
        <div key={i} className="flex flex-wrap gap-2 pl-4">
          <Input aria-label={`Component ${i + 1} name`} className="w-56" placeholder="Component" value={r.name} onChange={(e) => set(i, { name: e.target.value })} />
          <Input aria-label={`Component ${i + 1} unit`} className="w-20" placeholder="Unit" value={r.unit} onChange={(e) => set(i, { unit: e.target.value })} />
          <Input aria-label={`Component ${i + 1} quantity`} inputMode="decimal" className="w-24" placeholder="Quantity" value={r.quantity} onChange={(e) => set(i, { quantity: e.target.value })} />
        </div>
      ))}
      <div className="flex gap-2">
        <Button size="sm" variant="ghost" onClick={() => setRows([...rows, { ...EMPTY }])}>
          Add a component
        </Button>
        <Button size="sm" loading={make.isPending} disabled={!name.trim() || !rows.some((r) => r.name.trim() && r.quantity.trim())} onClick={submit}>
          Save bill of materials
        </Button>
      </div>
    </div>
  )
}

function Run({ clientId, bom, mayEdit }: { clientId: string; bom: Bom; mayEdit: boolean }) {
  const produce = useProduce(clientId)
  const remove = useRemoveBom(clientId)
  const [quantity, setQuantity] = useState('')
  const [date, setDate] = useState(today())
  const [extra, setExtra] = useState('')
  const [godown, setGodown] = useState('')
  const places = useQuery(godowns(clientId)).data ?? []
  const plan = useQuery(runPlan(clientId, bom.id, quantity, date, godown))
  const d = plan.data

  function go() {
    const extraPaise = extra.trim() ? parseRupees(extra) : 0
    if (extraPaise === null) return void toast.error('The extra cost is in rupees, like 500 or 500.50.')
    produce.mutate(
      { bom: bom.id, quantity, entry_date: date, extra_cost_paise: extraPaise, note: '', godown: godown || null },
      { onSuccess: () => { setQuantity(''); setExtra(''); toast.success(`Made ${bom.name}`) }, onError: (e) => toast.error(messageOf(e)) },
    )
  }

  return (
    <li className="grid gap-1 rounded-md border border-line p-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>
          <strong>{bom.name}</strong> <span className="text-muted-foreground">from {bom.components.map((c) => `${Number(c.quantity)} ${c.unit} ${c.name}`).join(', ')} per {Number(bom.output_quantity)} {bom.unit}</span>
        </span>
        {mayEdit && (
          <Button size="sm" variant="ghost" aria-label={`Remove the bill for ${bom.name}`} onClick={() => remove.mutate(bom.id, { onError: (e) => toast.error(messageOf(e)) })}>
            Remove
          </Button>
        )}
      </div>
      {mayEdit && (
        <div className="flex flex-wrap items-end gap-2">
          <Input aria-label={`Quantity of ${bom.name} to make`} inputMode="decimal" className="w-40" placeholder="Make how many" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          <input aria-label={`Production date for ${bom.name}`} type="date" className="h-9 rounded-md border border-border-strong bg-transparent px-2" value={date} onChange={(e) => setDate(e.target.value)} />
          {places.length > 0 && (
            <select aria-label={`Where to make ${bom.name}`} className="h-9 rounded-md border border-border-strong bg-transparent px-2" value={godown} onChange={(e) => setGodown(e.target.value)}>
              <option value="">Main location</option>
              {places.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          )}
          <Input aria-label={`Extra cost for ${bom.name}`} inputMode="decimal" className="w-32" placeholder="Extra cost (₹)" value={extra} onChange={(e) => setExtra(e.target.value)} />
          <Button size="sm" loading={produce.isPending} disabled={!d || d.short.length > 0} onClick={go}>
            Run production
          </Button>
        </div>
      )}
      {d && (
        <div className="text-xs">
          {d.components.map((c) => (
            <div key={c.name} className={c.enough ? 'text-muted-foreground' : ''}>
              {c.name}: needs {c.needed} {c.unit}, has {c.available}; costs {money(c.cost_paise)}
              {!c.enough && ' — short'}
            </div>
          ))}
          <div>Components cost {money(d.cost_paise)}. The finished goods are brought in at that plus any extra cost.</div>
        </div>
      )}
    </li>
  )
}

export function ManufacturingCard({ clientId, mayEdit }: { clientId: string; mayEdit: boolean }) {
  const list = useQuery(boms(clientId))
  return (
    <section aria-label="Manufacturing" className="grid gap-2 rounded-md border border-line p-3 text-sm">
      <h2 className="text-[15px] font-semibold text-heading">Manufacturing</h2>
      <p className="text-muted-foreground">
        Say what a finished item is made of. A production run takes the components out of stock at their average cost and brings the finished goods in. A run stops if any
        component is short.
      </p>
      {(list.data ?? []).length > 0 && (
        <ul className="grid gap-2" aria-label="Bills of materials">
          {list.data!.map((b) => (
            <Run key={b.id} clientId={clientId} bom={b} mayEdit={mayEdit} />
          ))}
        </ul>
      )}
      {mayEdit && <NewBom clientId={clientId} />}
    </section>
  )
}
