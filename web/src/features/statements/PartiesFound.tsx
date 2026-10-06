// Parties found in this client's statements: who the money moved to and from, for a person to tick the real ones.
//
// A statement names everyone, and most are not suppliers or customers: one-off payees, the client's own people. So nothing
// becomes a party on its own. The people who recur are listed with how often and how much, a role is suggested from the
// direction of the money, and ticking one makes the party and attaches its rows. Their own ledger is opened on first use.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'
import { messageOf } from '@/api/errors'
import { partyCandidates, useCreateFoundParties } from '@/api/queries/bills'
import { Money } from '@/components/ca/Money'
import { Button } from '@/components/ui/button'
import { Checkbox, Select } from '@/components/ui/controls'
import { formatDate, plural } from '@/lib/format'
import { useSession } from '@/session/session'

const ROLES = [
  ['VENDOR', 'Supplier'],
  ['CUSTOMER', 'Customer'],
  ['BOTH', 'Both'],
  ['OTHER', 'Other'],
] as const

export function PartiesFound({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const [oneOffs, setOneOffs] = useState(false)
  const list = useQuery(partyCandidates(clientId, oneOffs))
  const create = useCreateFoundParties(clientId)
  const [ticked, setTicked] = useState<Record<string, boolean>>({})
  const [roles, setRoles] = useState<Record<string, string>>({})
  const mayCreate = can('party.manage')

  if (!list.data) return null
  const items = list.data.candidates
  if (items.length === 0 && !oneOffs) return null
  const chosen = items.filter((c) => ticked[c.name])

  async function make() {
    try {
      const made = await create.mutateAsync(chosen.map((c) => ({ name: c.name, role: roles[c.name] ?? c.suggested_role })))
      toast.success(`${plural(made.created, 'party', 'parties')} created`)
      setTicked({})
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  return (
    <section className="grid gap-2" aria-labelledby="st-parties">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="st-parties" className="text-[15px] font-semibold text-heading">
          Parties found in these statements
        </h2>
        <Checkbox label="Include people seen only once" className="text-muted-foreground" checked={oneOffs} onChange={(e) => setOneOffs(e.target.checked)} />
      </div>
      <p className="text-sm text-muted-foreground">
        Tick the ones that are real suppliers or customers. Their rows are attached to them and later statements recognise them. Nothing is created until you do.
      </p>
      <ul className="grid gap-1">
        {items.map((c) => (
          <li key={c.name} className="flex flex-wrap items-center gap-3 rounded-md border bg-card p-2 text-sm">
            <Checkbox
              checked={!!ticked[c.name]}
              disabled={!mayCreate}
              onChange={(e) => setTicked({ ...ticked, [c.name]: e.target.checked })}
              aria-label={`Create ${c.name}`}
            />
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">{c.name}</div>
              <div className="text-xs text-muted-foreground">
                {plural(c.count, 'row')} · {formatDate(c.first)} to {formatDate(c.last)}
              </div>
            </div>
            <div className="flex gap-3 text-xs">
              {c.paid_paise > 0 && <span>Paid <Money display={c.paid_display} /></span>}
              {c.received_paise > 0 && <span>Received <Money display={c.received_display} /></span>}
            </div>
            <Select
              aria-label={`Role of ${c.name}`}
              className="w-32"
              disabled={!mayCreate}
              value={roles[c.name] ?? c.suggested_role}
              onChange={(e) => setRoles({ ...roles, [c.name]: e.target.value })}
            >
              {ROLES.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </Select>
          </li>
        ))}
      </ul>
      {mayCreate && (
        <div className="flex justify-end">
          <Button disabled={chosen.length === 0 || create.isPending} onClick={() => void make()}>
            {create.isPending ? 'Creating…' : `Create ${plural(chosen.length, 'party', 'parties')}`}
          </Button>
        </div>
      )}
    </section>
  )
}
