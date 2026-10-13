// A searchable menu for choosing one client out of many: type to narrow, arrows to move, Enter to choose. Each client shows how many alerts it has,
// and a red count where some are urgent, so eight clients or eighty are the same one control.

import { Check, ChevronDown, Search } from 'lucide-react'
import { useId, useState, type KeyboardEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { initialsOf } from '@/lib/useDebounced'
import { cn } from '@/lib/utils'

export interface ClientOption {
  id: string
  name: string
  count: number
  urgent: number
}

export function ClientFilter({ clients, value, total, onChange }: { clients: ClientOption[]; value?: string; total: number; onChange: (client?: string) => void }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [active, setActive] = useState(0)
  const listId = useId()
  const q = text.trim().toLowerCase()
  const matches = clients.filter((c) => c.name.toLowerCase().includes(q))
  // "All clients" leads the list, but only while nothing is being searched for.
  const options: { id?: string; name: string; count: number; urgent: number }[] = [...(q ? [] : [{ id: undefined, name: 'All clients', count: total, urgent: 0 }]), ...matches]
  const current = clients.find((c) => c.id === value)

  const choose = (index: number) => {
    const option = options[index]
    if (!option) return
    onChange(option.id)
    setOpen(false)
  }
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') setActive((a) => Math.min(a + 1, options.length - 1))
    else if (e.key === 'ArrowUp') setActive((a) => Math.max(a - 1, 0))
    else if (e.key === 'Home') setActive(0)
    else if (e.key === 'End') setActive(options.length - 1)
    else if (e.key === 'Enter') choose(active)
    else return
    e.preventDefault()
  }

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (next) {
          setText('')
          setActive(Math.max(0, value ? clients.findIndex((c) => c.id === value) + 1 : 0))
        }
      }}
    >
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="h-9 gap-2 rounded-full px-3.5" aria-haspopup="listbox">
          <span className="text-muted-foreground">Client:</span>
          <span className="max-w-40 truncate">{current?.name ?? 'All clients'}</span>
          <ChevronDown className="size-4 text-muted-foreground" aria-hidden />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" aria-label="Choose a client" className="w-80 p-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <input
            autoFocus
            role="combobox"
            aria-expanded
            aria-controls={listId}
            aria-activedescendant={options[active] ? `${listId}-${active}` : undefined}
            aria-label="Find a client"
            type="search"
            placeholder="Find a client"
            value={text}
            onChange={(e) => {
              setText(e.target.value)
              setActive(0)
            }}
            onKeyDown={onKey}
            className="h-9 w-full rounded-md border border-input bg-background pl-8 pr-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40"
          />
        </div>
        <ul id={listId} role="listbox" aria-label="Clients" className="mt-1.5 max-h-72 overflow-y-auto overscroll-contain">
          {options.map((o, i) => {
            const selected = o.id === value
            return (
              <li
                key={o.id ?? 'all'}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={selected}
                onMouseMove={() => setActive(i)}
                onClick={() => choose(i)}
                className={cn('flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 text-sm', i === active && 'bg-hover')}
              >
                {o.id ? (
                  <span aria-hidden className="grid size-6 shrink-0 place-items-center rounded-md border bg-muted text-[10px] font-bold">
                    {initialsOf(o.name).slice(0, 2)}
                  </span>
                ) : (
                  <span aria-hidden className="size-6 shrink-0" />
                )}
                <span className="min-w-0 flex-1 truncate">{o.name}</span>
                {o.urgent > 0 && (
                  <span className="num rounded-full border border-destructive/40 bg-destructive-bg px-2 text-xs font-bold text-destructive">
                    {o.urgent}
                    <span className="sr-only"> urgent</span>
                  </span>
                )}
                <span className="num text-xs text-muted-foreground">{o.count}</span>
                {selected && <Check className="size-4 text-primary" aria-hidden />}
              </li>
            )
          })}
          {options.length === 0 && <li className="px-3 py-4 text-center text-sm text-muted-foreground">No client by that name</li>}
        </ul>
      </PopoverContent>
    </Popover>
  )
}
