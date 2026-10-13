import { Search } from 'lucide-react'
import { Fragment, useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Kbd } from '@/components/ui/kbd'
import { comboKeys, comboOf, useHotkeyList, type Hotkey } from '@/lib/hotkeys'
import { cn } from '@/lib/utils'
import { searchCategories, shortcutCategories } from './shortcutGroups'

const LIT_MS = 1400
const SEQUENCE_MS = 900

/** A key's caps with a small plus between: Ctrl + K. */
function Caps({ combo }: { combo: string }) {
  const caps = comboKeys(combo)
  return (
    <span className="flex shrink-0 items-center gap-1">
      {caps.map((cap, i) => (
        <Fragment key={i}>
          {i > 0 && (
            <span aria-hidden className="text-[10px] text-faint">
              {combo.includes(' ') ? 'then' : '+'}
            </span>
          )}
          <Kbd className="h-6 min-w-6 px-1.5 text-[13px] font-semibold text-foreground">{cap}</Kbd>
        </Fragment>
      ))}
    </span>
  )
}

function Row({ hotkey, lit }: { hotkey: Hotkey; lit: boolean }) {
  return (
    <li
      data-lit={lit || undefined}
      className={cn('flex items-center justify-between gap-4 rounded-lg px-3 py-2 text-[15px] transition-colors duration-200', lit && 'bg-selected ring-1 ring-primary')}
    >
      <span>{hotkey.description}</span>
      <Caps combo={hotkey.combo} />
    </li>
  )
}

/** The keys that work on this screen right now, grouped: whatever is registered, and nothing that is not. (Used on the Preferences page.) */
export function ShortcutList() {
  const categories = shortcutCategories(useHotkeyList())
  return (
    <>
      {categories.map((c) => (
        <section key={c.id}>
          <h3 className="mb-1.5 text-xs font-semibold text-muted-foreground">{c.label}</h3>
          <ul className="grid gap-1">
            {c.items.map((hotkey) => (
              <li key={hotkey.combo + hotkey.description} className="flex items-center justify-between gap-4 py-1 text-sm">
                <span>{hotkey.description}</span>
                <Caps combo={hotkey.combo} />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </>
  )
}

/**
 * The keyboard guide: a search over every key, the headings down the left with how many each holds (the screen you are on marked
 * "here"), and the keys of the one chosen on the right. Press a shortcut and its row lights up, without doing what it does. In the dialog
 * the registry already leaves keys pressed inside a dialog alone; shown on a page (`inline`) the guide holds the key itself, so trying one
 * does not also run it.
 *
 * It returns two blocks (the search, then the lists) so the dialog can lay them out in its own grid; `inline` wraps them for a page.
 */
export function ShortcutGuide({ inline = false, searchRef }: { inline?: boolean; searchRef?: RefObject<HTMLInputElement | null> }) {
  const hotkeys = useHotkeyList()
  const categories = useMemo(() => shortcutCategories(hotkeys), [hotkeys])
  const [query, setQuery] = useState('')
  const [chosen, setChosen] = useState<string | null>(null)
  const [lit, setLit] = useState<Hotkey | null>(null)
  const own = useRef<HTMLInputElement>(null)
  const search = searchRef ?? own

  // Light the row of the key just pressed. A two-key sequence ("g l") lights on its second key.
  useEffect(() => {
    let lastKey: { combo: string; at: number } | null = null
    let timer: number | undefined
    const onKey = (e: KeyboardEvent) => {
      if (e.repeat || ['shift', 'control', 'alt', 'meta'].includes(e.key.toLowerCase())) return
      const combo = comboOf(e)
      const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement
      const modified = combo.includes('ctrl+') || combo.includes('alt+')
      if (typing && !modified) return
      if (combo === 'escape') return
      if (combo === '/') {
        e.preventDefault()
        search.current?.focus()
        return
      }
      const sequence = lastKey && Date.now() - lastKey.at < SEQUENCE_MS ? `${lastKey.combo} ${combo}` : null
      const hit = (sequence && hotkeys.find((h) => h.combo === sequence)) || hotkeys.find((h) => h.combo === combo)
      lastKey = { combo, at: Date.now() }
      if (!hit) return
      e.preventDefault()
      // On a page the key would otherwise do its job (go to another screen, say) as well as light its row.
      if (inline) e.stopPropagation()
      setQuery('')
      setChosen(categories.find((c) => c.items.includes(hit))?.id ?? null)
      setLit(hit)
      window.clearTimeout(timer)
      timer = window.setTimeout(() => setLit(null), LIT_MS)
    }
    window.addEventListener('keydown', onKey, true)
    return () => {
      window.removeEventListener('keydown', onKey, true)
      window.clearTimeout(timer)
    }
  }, [hotkeys, categories, inline, search])

  const searching = query.trim() !== ''
  const found = searchCategories(categories, query)
  const current = categories.find((c) => c.id === chosen) ?? categories[0]
  const shown = searching ? found : current ? [current] : []
  const total = found.reduce((n, c) => n + c.items.length, 0)

  const blocks = (
    <>
      <div>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <input
            ref={search}
            type="search"
            aria-label="Find a shortcut"
            placeholder="Find a shortcut, for example “post” or “ledger”"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape' && query) {
                e.stopPropagation()
                setQuery('')
              }
            }}
            className="h-11 w-full rounded-lg border border-input bg-background pl-9 pr-12 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40"
          />
          <Kbd aria-hidden className="absolute right-3 top-1/2 -translate-y-1/2">
            /
          </Kbd>
        </div>
      </div>
      <div className={cn('grid min-h-0 grid-cols-[13rem_minmax(0,1fr)] border-t max-sm:grid-cols-1 max-sm:grid-rows-[auto_minmax(0,1fr)]', inline && 'h-[34rem] rounded-xl border bg-card px-4')}>
        <nav aria-label="Shortcut headings" className="overflow-y-auto border-r py-3 pr-3 max-sm:flex max-sm:gap-1 max-sm:overflow-x-auto max-sm:border-b max-sm:border-r-0 max-sm:py-2 max-sm:pr-0">
          {categories.map((c) => {
            const count = searching ? (found.find((f) => f.id === c.id)?.items.length ?? 0) : c.items.length
            const on = !searching && c.id === current?.id
            return (
              <button
                key={c.id}
                type="button"
                aria-current={on ? 'true' : undefined}
                disabled={searching && count === 0}
                onClick={() => {
                  setQuery('')
                  setChosen(c.id)
                }}
                className={cn(
                  'flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-[15px] outline-none transition-colors duration-150 hover:bg-hover focus-visible:bg-hover max-sm:w-auto max-sm:shrink-0',
                  on && 'font-semibold',
                  searching && count === 0 && 'opacity-40',
                )}
              >
                <span>
                  {c.label}
                  {c.here && <span className="ml-2 align-middle text-[10px] font-bold uppercase tracking-wide text-primary">here</span>}
                </span>
                <span className="num text-xs text-muted-foreground">{count}</span>
              </button>
            )
          })}
        </nav>
        <div className="min-h-0 overflow-y-auto py-3 pl-4 max-sm:pl-0" aria-live="polite">
          {searching && (
            <p className="px-3 pb-2 text-xs text-muted-foreground">{total === 0 ? 'No shortcut matches that.' : `${total} ${total === 1 ? 'shortcut matches' : 'shortcuts match'}`}</p>
          )}
          {shown.map((c) => (
            <section key={c.id} aria-label={c.label} className="mb-3">
              {searching && <h3 className="px-3 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{c.label}</h3>}
              <ul className="grid gap-0.5">
                {c.items.map((hotkey) => (
                  <Row key={hotkey.combo + hotkey.description} hotkey={hotkey} lit={lit === hotkey} />
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </>
  )
  return inline ? <div className="grid gap-4">{blocks}</div> : blocks
}

export function ShortcutSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const search = useRef<HTMLInputElement>(null)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="h-[min(44rem,calc(100svh-2rem))] max-w-4xl grid-rows-[auto_auto_minmax(0,1fr)] gap-4 overflow-hidden p-0 [&>*]:px-6 [&>*:first-child]:pt-6"
        aria-describedby="shortcut-help"
        onOpenAutoFocus={(e) => {
          // The search is where a person starts typing; "/" brings it back.
          e.preventDefault()
          search.current?.focus()
        }}
      >
        <DialogHeader>
          <DialogTitle className="text-xl">Keyboard shortcuts</DialogTitle>
          <DialogDescription id="shortcut-help">Press any shortcut to see its row light up.</DialogDescription>
        </DialogHeader>
        <ShortcutGuide searchRef={search} />
      </DialogContent>
    </Dialog>
  )
}
