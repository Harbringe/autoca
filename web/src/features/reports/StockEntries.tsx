// Opening stock and count adjustments: the stock movements no invoice carries.
//
// Purchases and sales move stock through their own invoice lines. What a client held when the books began, and what a physical
// count found different (damage, shortage, samples), have no invoice, so they are recorded here and the report counts them.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { useInvalidateClient, V1 } from '@/api/queries/clients'
import { Button } from '@/components/ui/button'
import { Select, Textarea } from '@/components/ui/controls'
import { DateInput } from '@/components/ui/date-input'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { formatDate, parseRupees } from '@/lib/format'

interface Row {
  id: string
  kind: string
  kind_display: string
  entry_date: string
  direction: string
  name: string
  unit: string
  quantity: string
  value_paise: number
  note: string
}

export function StockEntries({ clientId, fy, onClose }: { clientId: string; fy: number; onClose: () => void }) {
  const invalidate = useInvalidateClient(clientId)
  const rows = useQuery({
    queryKey: ['stock-entries', clientId],
    queryFn: () => raw.get<{ results: Row[] }>(`${V1}/clients/${clientId}/stock-entries/`),
  })
  const [kind, setKind] = useState('OPENING')
  const [direction, setDirection] = useState('OUT')
  const [name, setName] = useState('')
  const [unit, setUnit] = useState('')
  const [quantity, setQuantity] = useState('')
  const [value, setValue] = useState('')
  const [date, setDate] = useState(`${fy}-04-01`)
  const [note, setNote] = useState('')

  async function save() {
    try {
      await raw.post(`${V1}/clients/${clientId}/stock-entries/`, {
        kind, entry_date: date, direction, name, unit, quantity, value_paise: parseRupees(value || '0') ?? 0, note,
      })
      toast.success('Recorded')
      setName('')
      setQuantity('')
      setValue('')
      setNote('')
      await rows.refetch()
      await invalidate()
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  async function remove(id: string) {
    try {
      await raw.post(`${V1}/clients/${clientId}/stock-entries/${id}/remove/`, {})
      await rows.refetch()
      await invalidate()
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Opening stock and adjustments</DialogTitle>
          <DialogDescription>
            What the client held when its books began, and what a physical count found different. Purchases and sales are counted from their invoices.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <Field label="What is it">
            {(p) => (
              <Select {...p} value={kind} onChange={(e) => { setKind(e.target.value); setDate(e.target.value === 'OPENING' ? `${fy}-04-01` : date) }}>
                <option value="OPENING">Opening stock</option>
                <option value="ADJUSTMENT">Count adjustment</option>
              </Select>
            )}
          </Field>
          {kind === 'ADJUSTMENT' && (
            <Field label="Found">
              {(p) => (
                <Select {...p} value={direction} onChange={(e) => setDirection(e.target.value)}>
                  <option value="OUT">Less than the register (shortage, damage)</option>
                  <option value="IN">More than the register</option>
                </Select>
              )}
            </Field>
          )}
          <Field label="Item">{(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Quantity">{(p) => <Input {...p} inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />}</Field>
            <Field label="Unit">{(p) => <Input {...p} placeholder="kg, pcs, bag" value={unit} onChange={(e) => setUnit(e.target.value)} />}</Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Value carried at (₹)">{(p) => <Input {...p} inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} />}</Field>
            <Field label="Date">{(p) => <DateInput {...p} value={date} onChange={(e) => setDate(e.target.value)} />}</Field>
          </div>
          {kind === 'ADJUSTMENT' && <Field label="Why">{(p) => <Textarea {...p} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>}
          <div className="flex justify-end">
            <Button onClick={() => void save()} disabled={!name.trim() || !quantity.trim()}>Record</Button>
          </div>
        </div>
        {(rows.data?.results ?? []).length > 0 && (
          <ul className="grid gap-1 border-t pt-3 text-sm">
            {rows.data!.results.map((r) => (
              <li key={r.id} className="flex items-center justify-between gap-3">
                <span>
                  {r.kind_display}: {r.direction === 'OUT' ? '−' : '+'}{Number(r.quantity)} {r.unit} {r.name} · {formatDate(r.entry_date)}
                  {r.note ? ` · ${r.note}` : ''}
                </span>
                <Button size="sm" variant="ghost" onClick={() => void remove(r.id)}>Remove</Button>
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  )
}
