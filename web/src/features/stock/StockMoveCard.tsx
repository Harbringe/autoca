// Move stock from one place to another: out of one godown and into the other. The business holds the same stock before and after.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { godowns, useTransferStock } from '@/api/queries/godowns'
import { stockItems } from '@/api/queries/stockItems'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select } from '@/components/ui/controls'
import { Input } from '@/components/ui/input'
import { toast } from '@/lib/toast'
import { say } from './say'

const MAIN = 'main'
const today = () => new Date().toISOString().slice(0, 10)

export function StockMoveCard({ clientId }: { clientId: string }) {
  const places = useQuery(godowns(clientId)).data ?? []
  const items = useQuery(stockItems(clientId)).data ?? []
  const move = useTransferStock(clientId)
  const [name, setName] = useState('')
  const [quantity, setQuantity] = useState('')
  const [date, setDate] = useState(today())
  const [from, setFrom] = useState(MAIN)
  const [to, setTo] = useState(places[0]?.id ?? MAIN)

  const same = from === to
  const ready = name.trim() !== '' && Number(quantity) > 0 && !same

  async function go() {
    try {
      await move.mutateAsync({
        entry_date: date,
        name: name.trim(),
        unit: items.find((i) => i.name.toLowerCase() === name.trim().toLowerCase())?.unit,
        quantity: quantity.trim(),
        from_godown: from === MAIN ? null : from,
        to_godown: to === MAIN ? null : to,
      })
      setQuantity('')
      toast.success('Stock moved')
    } catch (e) {
      toast.error(say(e))
    }
  }

  const options = (
    <>
      <option value={MAIN}>Main location</option>
      {places.map((g) => (
        <option key={g.id} value={g.id}>
          {g.name}
        </option>
      ))}
    </>
  )

  return (
    <Card className="grid gap-3 p-4">
      <h2 className="font-medium">Move stock between godowns</h2>
      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-0.5 text-xs text-muted-foreground">
          <span aria-hidden>Item</span>
          <Input aria-label="Item to move" list="stock-move-items" className="w-56" value={name} onChange={(e) => setName(e.target.value)} />
          <datalist id="stock-move-items">
            {items.map((i) => (
              <option key={i.id} value={i.name} />
            ))}
          </datalist>
        </label>
        <label className="grid gap-0.5 text-xs text-muted-foreground">
          <span aria-hidden>Quantity</span>
          <Input aria-label="Quantity to move" inputMode="decimal" className="w-24" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </label>
        <label className="grid gap-0.5 text-xs text-muted-foreground">
          <span aria-hidden>From</span>
          <Select aria-label="Move from" value={from} onChange={(e) => setFrom(e.target.value)}>
            {options}
          </Select>
        </label>
        <label className="grid gap-0.5 text-xs text-muted-foreground">
          <span aria-hidden>To</span>
          <Select aria-label="Move to" value={to} onChange={(e) => setTo(e.target.value)}>
            {options}
          </Select>
        </label>
        <label className="grid gap-0.5 text-xs text-muted-foreground">
          <span aria-hidden>Date</span>
          <Input aria-label="Date of the move" type="date" className="w-40" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <Button loading={move.isPending} disabled={!ready} onClick={() => void go()}>
          Move stock
        </Button>
      </div>
      {same && <p className="text-sm text-muted-foreground">Choose two different places.</p>}
    </Card>
  )
}
