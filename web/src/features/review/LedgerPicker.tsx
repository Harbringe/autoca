// Choosing a ledger the way Tally does: type a few letters, the list narrows, Enter takes it.
//
// Only ledgers that can actually be used are offered -- active, accepted, and never the bank
// account the row came from (that would post Dr Bank / Cr Bank). When nothing matches, the
// last line offers to create a ledger with what was typed, under a group the person chooses.

import { useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { GROUP_LABEL, type LedgerAccount } from '@/api/types'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { NewAccountDialog } from './NewAccountDialog'

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
  const chosen = ledgers.find((l) => l.id === value) ?? null
  const [text, setText] = useState('')
  const [active, setActive] = useState(0)
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState<{ name: string; group: string } | null>(null)
  const listRef = useRef<HTMLUListElement>(null)

  const matches = useMemo(() => {
    const q = text.trim().toLowerCase()
    const hits = q ? ledgers.filter((l) => l.name.toLowerCase().includes(q)) : ledgers
    // With nothing typed the list reads as the chart of accounts: by account group, then name. Once something is typed,
    // names that start with it come first, as in Tally's list.
    const groupOf = (l: LedgerAccount) => GROUP_LABEL[l.group ?? ''] ?? l.group ?? ''
    return [...hits].sort((a, b) => {
      if (!q) return groupOf(a).localeCompare(groupOf(b)) || a.name.localeCompare(b.name)
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

  return (
    <div className="relative grid gap-1.5">
      {creating && (
        <NewAccountDialog
          clientId={clientId}
          ledgers={ledgers}
          initialName={creating.name}
          initialGroup={creating.group}
          onCreated={(made) => {
            onChange(made.id)
            setCreating(null)
            setText('')
          }}
          onClose={() => setCreating(null)}
        />
      )}
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
          {matches.map((l, i) => {
            const group = GROUP_LABEL[l.group ?? ''] ?? l.group ?? ''
            const previous = i > 0 ? (GROUP_LABEL[matches[i - 1]!.group ?? ''] ?? matches[i - 1]!.group ?? '') : null
            const heading = !text.trim() && group !== previous
            return (
              <li key={l.id} role="presentation" className="contents">
                {heading && (
                  <div role="presentation" className="sticky top-0 bg-popover px-2 pb-0.5 pt-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {group}
                  </div>
                )}
                <div
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
                  {text.trim() && <span className="shrink-0 text-xs text-muted-foreground">{group}</span>}
                </div>
              </li>
            )
          })}
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
