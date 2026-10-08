// Choosing a ledger the way Tally does: type a few letters, the list narrows, Enter takes it.
//
// Only ledgers that can actually be used are offered -- active, accepted, and never the bank
// account the row came from (that would post Dr Bank / Cr Bank). When nothing matches, the
// last line offers to create a ledger with what was typed, under a group the person chooses.

import { useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { useInvalidateClient, V1 } from '@/api/queries/clients'
import { GROUP_LABEL, LEDGER_GROUPS, type LedgerAccount } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/controls'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'

export function usableLedgers(all: LedgerAccount[] | undefined, excludeName?: string | null): LedgerAccount[] {
  return (all ?? []).filter((l) => l.status === 'ACTIVE' && l.is_active && l.name !== excludeName)
}

export function LedgerPicker({
  clientId,
  ledgers,
  value,
  onChange,
  inputRef,
  label = 'Ledger',
  suggestedGroup,
}: {
  clientId: string
  ledgers: LedgerAccount[]
  value: string | null
  onChange: (id: string) => void
  inputRef?: React.RefObject<HTMLInputElement | null>
  label?: string
  /** The group to offer first when creating a new ledger (expense for money out, income for money in). */
  suggestedGroup?: string
}) {
  const { can } = useSession()
  const invalidate = useInvalidateClient(clientId)
  const chosen = ledgers.find((l) => l.id === value) ?? null
  const [text, setText] = useState('')
  const [active, setActive] = useState(0)
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState<{ name: string; group: string } | null>(null)
  const listRef = useRef<HTMLUListElement>(null)

  const matches = useMemo(() => {
    const q = text.trim().toLowerCase()
    const hits = q ? ledgers.filter((l) => l.name.toLowerCase().includes(q)) : ledgers
    // Names that start with what was typed come first, as in Tally's list.
    return [...hits].sort((a, b) => {
      const as = a.name.toLowerCase().startsWith(q) ? 0 : 1
      const bs = b.name.toLowerCase().startsWith(q) ? 0 : 1
      return as - bs || a.name.localeCompare(b.name)
    })
  }, [ledgers, text])
  const exact = ledgers.some((l) => l.name.toLowerCase() === text.trim().toLowerCase())
  const offerCreate = can('ledger.manage') && !exact
  const options = matches.length + (offerCreate ? 1 : 0)

  function pick(i: number) {
    if (i < matches.length) {
      onChange(matches[i]!.id)
      setText('')
      setOpen(false)
    } else if (offerCreate) {
      setCreating({ name: text.trim(), group: suggestedGroup ?? 'INDIRECT_EXPENSE' })
      setOpen(false)
    }
  }

  function key(e: KeyboardEvent) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setOpen(true)
      setActive((a) => Math.min(a + 1, options - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => Math.max(a - 1, 0))
    } else if (e.key === 'Enter' && open && options > 0) {
      e.preventDefault()
      e.stopPropagation()
      pick(active)
    } else if (e.key === 'Escape' && open) {
      e.stopPropagation()
      setOpen(false)
    }
  }

  async function create() {
    if (!creating) return
    try {
      const made = await raw.post<LedgerAccount>(`${V1}/clients/${clientId}/ledgers/`, { name: creating.name, group: creating.group })
      await invalidate()
      onChange(made.id)
      toast.success(`Ledger “${made.name}” created under ${GROUP_LABEL[made.group ?? ''] ?? made.group}`)
      setCreating(null)
      setText('')
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  if (creating) {
    return (
      <div className="grid gap-2 rounded-md border bg-muted/40 p-3">
        <div className="text-[13px] font-medium">New ledger</div>
        <Input aria-label="New ledger name" value={creating.name} onChange={(e) => setCreating({ ...creating, name: e.target.value })} />
        <Select aria-label="Group" value={creating.group} onChange={(e) => setCreating({ ...creating, group: e.target.value })}>
          {LEDGER_GROUPS.filter(([g]) => g !== 'BANK' && g !== 'SUSPENSE').map(([g, l]) => (
            <option key={g} value={g}>{l}</option>
          ))}
        </Select>
        <p className="text-xs text-muted-foreground">The name must match the ledger in the client’s Tally company exactly.</p>
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={() => setCreating(null)}>Cancel</Button>
          <Button size="sm" onClick={() => void create()} disabled={creating.name.trim().length < 2}>Create and use</Button>
        </div>
      </div>
    )
  }

  return (
    <div className="relative grid gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <label className="text-[13px] font-medium" htmlFor={`${clientId}-ledger`}>
          {label}
        </label>
        {can('ledger.manage') && (
          <button
            type="button"
            className="text-xs font-medium text-link hover:underline"
            onClick={() => setCreating({ name: text.trim(), group: suggestedGroup ?? 'INDIRECT_EXPENSE' })}
          >
            + New ledger
          </button>
        )}
      </div>
      <Input
        id={`${clientId}-ledger`}
        ref={inputRef}
        role="combobox"
        aria-expanded={open}
        aria-controls={`${clientId}-ledger-list`}
        autoComplete="off"
        placeholder={chosen ? chosen.name : 'Type to search ledgers…'}
        className={cn(chosen && 'placeholder:text-foreground placeholder:font-medium')}
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          setActive(0)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={key}
      />
      {chosen && !open && <div className="text-xs text-muted-foreground">{GROUP_LABEL[chosen.group ?? ''] ?? chosen.group}</div>}
      {open && options > 0 && (
        <ul
          id={`${clientId}-ledger-list`}
          ref={listRef}
          role="listbox"
          className="absolute top-full z-40 mt-1 max-h-64 w-full overflow-y-auto rounded-md border bg-popover p-1 shadow-md"
        >
          {matches.map((l, i) => (
            <li
              key={l.id}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault()
                pick(i)
              }}
              onMouseEnter={() => setActive(i)}
              className={cn('flex cursor-default justify-between gap-3 rounded-sm px-2 py-1.5 text-sm', i === active && 'bg-hover')}
            >
              <span className="truncate">{l.name}</span>
              <span className="shrink-0 text-xs text-muted-foreground">{GROUP_LABEL[l.group ?? ''] ?? l.group}</span>
            </li>
          ))}
          {offerCreate && (
            <li
              role="option"
              aria-selected={active === matches.length}
              onMouseDown={(e) => {
                e.preventDefault()
                pick(matches.length)
              }}
              className={cn('cursor-default rounded-sm px-2 py-1.5 text-sm text-info', active === matches.length && 'bg-hover')}
            >
              {text.trim().length >= 2 ? `+ Create ledger “${text.trim()}”` : '+ Create a new ledger…'}
            </li>
          )}
        </ul>
      )}
    </div>
  )
}
