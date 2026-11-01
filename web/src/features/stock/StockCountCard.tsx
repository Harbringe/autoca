// A physical count: what was found on the shelf against what the books say. A difference is booked as a stock adjustment.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { godowns, useCountStock } from '@/api/queries/godowns'
import { stockItems } from '@/api/queries/stockItems'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select } from '@/components/ui/controls'
import { Input } from '@/components/ui/input'
import { toast } from '@/lib/toast'
import { say } from './say'

const MAIN = ''
const today = () => new Date().toISOString().slice(0, 10)

export function StockCountCard({ clientId }: { clientId: string }) {
  const places = useQuery(godowns(clientId)).data ?? []
  const items = useQuery(stockItems(clientId)).data ?? []
  const count = useCountStock(clientId)
  const [name, setName] = useState('')
  const [counted, setCounted] = useState('')
  const [date, setDate] = useState(today())
  const [where, setWhere] = useState(MAIN)

  async function go() {
    try {
      const result = await count.mutateAsync({
        entry_date: date,
        name: name.trim(),
        unit: items.find((i) => i.name.toLowerCase() === name.trim().toLowerCase())?.unit,
        counted_quantity: counted.trim(),
        godown: where || null,
      })
      const diff = Number(result.difference)
      if (diff === 0) toast.success(`The count agrees with the books: ${result.book_quantity} on hand.`)
      else
        toast.success(
          `Books said ${result.book_quantity}, counted ${result.counted_quantity}: ${Math.abs(diff)} ${diff < 0 ? 'short, booked as stock out' : 'over, booked as stock in'}.`,
        )
      setCounted('')
    } catch (e) {
      toast.error(say(e))
    }
  }

  return (
    <Card className="grid gap-3 p-4">
      <h2 className="font-medium">Physical stock count</h2>
      <p className="text-sm text-muted-foreground">
        Enter what you found. If it differs from the books, the difference is booked as a stock adjustment dated that day; if it agrees, nothing is booked.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-0.5 text-xs text-muted-foreground">
          <span aria-hidden>Item</span>
          <Input aria-label="Item counted" list="stock-count-items" className="w-56" value={name} onChange={(e) => setName(e.target.value)} />
          <datalist id="stock-count-items">
            {items.map((i) => (
              <option key={i.id} value={i.name} />
            ))}
          </datalist>
        </label>
        <label className="grid gap-0.5 text-xs text-muted-foreground">
          <span aria-hidden>Counted</span>
          <Input aria-label="Counted quantity" inputMode="decimal" className="w-24" value={counted} onChange={(e) => setCounted(e.target.value)} />
        </label>
        {places.length > 0 && (
          <label className="grid gap-0.5 text-xs text-muted-foreground">
            <span aria-hidden>Where</span>
            <Select aria-label="Counted in" value={where} onChange={(e) => setWhere(e.target.value)}>
              <option value={MAIN}>Main location</option>
              {places.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </Select>
          </label>
        )}
        <label className="grid gap-0.5 text-xs text-muted-foreground">
          <span aria-hidden>Date</span>
          <Input aria-label="Date of the count" type="date" className="w-40" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <Button loading={count.isPending} disabled={!name.trim() || counted.trim() === ''} onClick={() => void go()}>
          Record count
        </Button>
      </div>
    </Card>
  )
}
