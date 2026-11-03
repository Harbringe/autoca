// The places the client keeps stock. Stock with no godown is in the main location.

import { useQuery } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useState } from 'react'
import { godowns, useMakeGodown, useRemoveGodown } from '@/api/queries/godowns'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { toast } from '@/lib/toast'
import { say } from './say'

export function GodownsCard({ clientId, mayEdit }: { clientId: string; mayEdit: boolean }) {
  const list = useQuery(godowns(clientId))
  const make = useMakeGodown(clientId)
  const remove = useRemoveGodown(clientId)
  const [name, setName] = useState('')

  async function add() {
    try {
      await make.mutateAsync(name.trim())
      setName('')
      toast.success('Godown added')
    } catch (e) {
      toast.error(say(e))
    }
  }

  async function drop(id: string) {
    try {
      await remove.mutateAsync(id)
    } catch (e) {
      toast.error(say(e))
    }
  }

  const rows = list.data ?? []
  return (
    <Card className="grid gap-3 p-4">
      <h2 className="font-medium">Godowns</h2>
      <p className="text-sm text-muted-foreground">
        The places this client keeps stock: a shop, a yard, a rented warehouse. Stock with no godown named is in the main location. Moving stock between
        places does not change how much the business holds.
      </p>
      {rows.length > 0 && (
        <ul aria-label="Godowns" className="divide-y divide-border-strong rounded-lg border border-border-strong text-sm">
          {rows.map((g) => (
            <li key={g.id} className="flex items-center justify-between gap-2 px-3 py-2">
              <span className="font-medium">{g.name}</span>
              {mayEdit && (
                <Button size="sm" variant="ghost" aria-label={`Remove ${g.name}`} onClick={() => void drop(g.id)}>
                  <Trash2 />
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {mayEdit && (
        <div className="flex flex-wrap items-end gap-2">
          <Input aria-label="Godown name" placeholder="Name, e.g. Shop" className="w-56" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && name.trim() && !make.isPending) void add() }} />
          <Button loading={make.isPending} disabled={!name.trim()} onClick={() => void add()}>
            Add godown
          </Button>
        </div>
      )}
    </Card>
  )
}
