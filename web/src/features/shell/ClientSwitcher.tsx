// The client switcher: a small popover from the client's name, not a page. Search at the top (focused),
// Pinned and Recent underneath, "All N clients" at the foot. Arrow keys move, Enter opens, Esc closes.
// Picking a client keeps the screen you are on (Day Book stays Day Book), through switchClientPath.

import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useRouterState } from '@tanstack/react-router'
import { Search, Star } from 'lucide-react'
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { clientsList } from '@/api/queries/clients'
import { Kbd } from '@/components/ui/kbd'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { switchClientPath } from '@/lib/modules'
import { useClientMemory } from '@/lib/recentClients'
import { useDebounced } from '@/lib/useDebounced'
import { cn } from '@/lib/utils'
import { useClientNames } from './clientHeader'
import { registerSwitcher } from './switcherBus'

interface Option {
  id: string
  name: string
  group: 'Pinned' | 'Recent' | 'Clients' | 'Results'
}

const SHOWN = 8

/** Wraps the trigger (one button) and anchors the popover to it. */
export function ClientSwitcher({ currentId, children, align = 'start' }: { currentId: string; children: ReactNode; align?: 'start' | 'center' | 'end' }) {
  const [open, setOpen] = useState(false)
  useEffect(() => registerSwitcher(() => setOpen(true)), [])
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>{children}</PopoverTrigger>
      <PopoverContent
        align={align}
        aria-label="Switch client"
        className="w-[360px] max-w-[calc(100vw-1rem)]"
        onOpenAutoFocus={(e) => {
          e.preventDefault()
          ;(e.currentTarget as HTMLElement).querySelector<HTMLInputElement>('input')?.focus()
        }}
      >
        <SwitcherBody currentId={currentId} close={() => setOpen(false)} />
      </PopoverContent>
    </Popover>
  )
}

function SwitcherBody({ currentId, close }: { currentId: string; close: () => void }) {
  const navigate = useNavigate()
  const path = useRouterState({ select: (s) => s.location.pathname })
  const { recent, pinned } = useClientMemory()
  const [input, setInput] = useState('')
  const typed = input.trim()
  const term = useDebounced(typed)
  const found = useQuery(clientsList(term))
  const all = useQuery(clientsList(''))
  const pinnedNamed = useClientNames(pinned)
  const recentNamed = useClientNames(recent.filter((id) => !pinned.includes(id)))
  const listId = useId()

  // Results are for the text as it was a moment ago; until they catch up they are not offered, so
  // Enter can never open a client the person has already typed past.
  const settled = term === typed && !found.isPlaceholderData
  const options = ((): Option[] => {
    if (typed) return settled ? (found.data?.results ?? []).slice(0, SHOWN).map((c) => ({ id: c.id, name: c.name, group: 'Results' as const })) : []
    const own: Option[] = [
      ...pinnedNamed.map((c) => ({ ...c, group: 'Pinned' as const })),
      ...recentNamed.map((c) => ({ ...c, group: 'Recent' as const })),
    ]
    if (own.length > 0) return own
    return (all.data?.results ?? []).slice(0, SHOWN).map((c) => ({ id: c.id, name: c.name, group: 'Clients' as const }))
  })()

  const [activeId, setActiveId] = useState<string | null>(null)
  const index = Math.max(0, options.findIndex((o) => o.id === activeId))
  const active = options[index]
  const activeRef = useRef<HTMLLIElement | null>(null)
  useEffect(() => {
    activeRef.current?.scrollIntoView?.({ block: 'nearest' })
  }, [active?.id])

  const pick = (option: Option | undefined) => {
    if (!option) return
    close()
    if (option.id !== currentId) void navigate({ to: switchClientPath(path, option.id) as never })
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (options.length === 0) return
      const next = (index + (e.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length
      setActiveId(options[next]!.id)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      pick(active)
    }
  }

  const total = all.data?.count
  const searching = typed !== '' && (!settled || found.isFetching)
  const groups = (['Pinned', 'Recent', 'Clients', 'Results'] as const).filter((g) => options.some((o) => o.group === g))

  return (
    <div>
      <div className="border-b p-2.5">
        <div className="flex h-10 items-center gap-2 rounded-md border-2 border-ring bg-card px-2.5 text-sm">
          <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <input
            role="combobox"
            aria-expanded
            aria-controls={listId}
            aria-activedescendant={active ? `${listId}-${active.id}` : undefined}
            aria-autocomplete="list"
            aria-label="Search clients"
            autoComplete="off"
            spellCheck={false}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={total ? `Search ${total} clients` : 'Search clients'}
            className="h-full min-w-0 flex-1 bg-transparent outline-none placeholder:text-faint"
          />
        </div>
      </div>
      <div className="max-h-[min(60vh,22rem)] overflow-y-auto overscroll-contain py-1">
        {found.isError && typed ? (
          <p role="alert" className="px-4 py-3 text-sm">
            Could not load clients. <button type="button" className="font-medium text-link underline underline-offset-2" onClick={() => void found.refetch()}>Try again</button>
          </p>
        ) : options.length === 0 ? (
          <p role="status" className="px-4 py-5 text-center text-sm text-muted-foreground">
            {typed ? (searching ? 'Searching…' : `No client matches “${typed}”.`) : all.isPending ? 'Loading clients…' : 'No clients yet.'}
          </p>
        ) : (
          <ul id={listId} role="listbox" aria-label="Clients">
            {groups.map((group) => (
              <li key={group} role="presentation">
                <div className="px-3.5 pb-1 pt-2.5 text-xs font-medium uppercase tracking-[0.06em] text-muted-foreground">{group}</div>
                <ul role="presentation">
                  {options
                    .filter((o) => o.group === group)
                    .map((o) => {
                      const isActive = o.id === active?.id
                      return (
                        <li
                          key={o.id}
                          id={`${listId}-${o.id}`}
                          ref={isActive ? activeRef : undefined}
                          role="option"
                          aria-selected={isActive}
                          onMouseMove={() => setActiveId(o.id)}
                          onClick={() => pick(o)}
                          className={cn('flex min-h-9 cursor-pointer items-center gap-2.5 px-3.5 py-1.5 text-sm max-sm:min-h-11', isActive && 'bg-hover')}
                        >
                          {group === 'Pinned' ? <Star className="size-3.5 shrink-0 fill-current text-accent-foreground" aria-hidden /> : null}
                          <span className="min-w-0 flex-1 break-words">{o.name}</span>
                          {o.id === currentId && <span className="shrink-0 text-xs text-muted-foreground">Current</span>}
                        </li>
                      )
                    })}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="flex items-center justify-between gap-3 border-t px-3.5 py-2.5 text-[13px]">
        <Link to="/clients" onClick={close} className="font-medium text-link underline underline-offset-2">
          {total !== undefined ? `All ${total} clients` : 'All clients'}
        </Link>
        <span className="flex items-center gap-1 text-muted-foreground max-sm:hidden" aria-label="Shortcut: Alt C">
          <Kbd>Alt</Kbd>
          <Kbd>C</Kbd>
        </span>
      </div>
    </div>
  )
}
