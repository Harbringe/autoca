// Re-spell the names already stored the way new ones are written (ALL CAPS and stray spacing become proper case).
//
// New names are tidied as they are typed or read from an invoice; the ones stored before that stay as they were. This shows
// each change next to the old spelling, lets a person untick any, and renames only what stays ticked.

import { useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { useInvalidateClient, V1 } from '@/api/queries/clients'
import type { Party } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/controls'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { normaliseName } from '@/lib/names'

export function proposals(parties: Party[]): { party: Party; to: string }[] {
  return parties
    .map((party) => ({ party, to: normaliseName(party.canonical_name) }))
    .filter(({ party, to }) => to && to !== party.canonical_name)
}

export function TidyNames({ clientId, parties, onClose }: { clientId: string; parties: Party[]; onClose: () => void }) {
  const invalidate = useInvalidateClient(clientId)
  const changes = proposals(parties)
  const [off, setOff] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const chosen = changes.filter((c) => !off.has(c.party.id))

  async function apply() {
    setBusy(true)
    let done = 0
    const failed: string[] = []
    for (const { party, to } of chosen) {
      try {
        await raw.patch(`${V1}/clients/${clientId}/parties/${party.id}/`, { canonical_name: to })
        done += 1
      } catch (e) {
        failed.push(`${party.canonical_name}: ${messageOf(e)}`)
      }
    }
    await invalidate()
    setBusy(false)
    if (done) toast.success(`${done} name${done === 1 ? '' : 's'} re-spelled`)
    if (failed.length) toast.error(failed.slice(0, 3).join('\n'))
    if (!failed.length) onClose()
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Tidy stored names</DialogTitle>
          <DialogDescription>
            {changes.length === 0
              ? 'Every name is already written the way new ones are.'
              : 'Names read before the spelling rules existed. Untick any you want left as they are.'}
          </DialogDescription>
        </DialogHeader>
        <ul className="grid gap-2 text-sm">
          {changes.map(({ party, to }) => (
            <li key={party.id}>
              <Checkbox
                label={<span><span className="text-muted-foreground line-through">{party.canonical_name}</span> → <strong>{to}</strong></span>}
                checked={!off.has(party.id)}
                onChange={(e) => setOff((prev) => { const next = new Set(prev); if (e.target.checked) next.delete(party.id); else next.add(party.id); return next })}
              />
            </li>
          ))}
        </ul>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Close</Button>
          {changes.length > 0 && <Button onClick={() => void apply()} disabled={busy || chosen.length === 0}>Re-spell {chosen.length}</Button>}
        </div>
      </DialogContent>
    </Dialog>
  )
}
