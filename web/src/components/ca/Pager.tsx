// Paging for a long list that is already in the browser: "Showing 51–100 of 536", Previous, page numbers, Next. It appears only
// when the list is longer than one page, so a short list looks exactly as it did. A list renders one page of rows instead of
// hundreds, which is what keeps a long statement light on an old machine.

import { usePageSize, type PageSection } from '@/lib/pageSizes'
import { useEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { Button } from '@/components/ui/button'

/** Rows on a page. A few dozen is a screen or two of work, and few enough that opening a row stays instant. */
export const PAGE_SIZE = 50

export interface Paged<T> {
  /** This page's rows. */
  items: T[]
  page: number
  pages: number
  /** 1-based position of the first and last row shown, and how many there are in all. */
  from: number
  to: number
  total: number
  /** False for a list that fits on one page, so nothing needs a pager. */
  paged: boolean
  setPage: (page: number) => void
  /** Turn to the page that holds the row at `index` (0-based) of the whole list. */
  reveal: (index: number) => void
}

/**
 * One page of `items`. `resetKey` names what the list is a list *of* (a filter, a stage, a sort): when it changes the list goes back
 * to page 1, and a page beyond the end (rows were posted and left) is brought back to the last one.
 */
export function usePaged<T>(items: readonly T[], resetKey: string, size = PAGE_SIZE): Paged<T> {
  const [state, setState] = useState({ key: resetKey, page: 1 })
  const pages = Math.max(1, Math.ceil(items.length / size))
  const page = Math.min(state.key === resetKey ? state.page : 1, pages)
  const setPage = (next: number) => setState({ key: resetKey, page: Math.min(Math.max(next, 1), pages) })
  return {
    items: items.slice((page - 1) * size, page * size),
    page,
    pages,
    from: items.length === 0 ? 0 : (page - 1) * size + 1,
    to: Math.min(page * size, items.length),
    total: items.length,
    paged: items.length > size,
    setPage,
    reveal: (index) => {
      const target = Math.floor(Math.max(index, 0) / size) + 1
      if (target !== page) setPage(target)
    },
  }
}

/**
 * A short fade on `ref` when `key` changes (a new page), so turning the page reads as a change and not a jump. Opacity only, which a
 * browser does without repainting the rows, and none at all for a person who has asked for less motion. Not on the first showing.
 */
export function useFadeOnChange(ref: RefObject<HTMLElement | null>, key: unknown) {
  const shown = useRef(false)
  useEffect(() => {
    if (!shown.current) {
      shown.current = true
      return
    }
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    ref.current?.animate?.([{ opacity: 0.25 }, { opacity: 1 }], { duration: 200, easing: 'ease-out' })
  }, [ref, key])
}

/**
 * The page number you are on, which becomes a box when you press it: type another page, Enter to go there, Esc to leave it.
 * A page beyond the end goes to the last page and one before the start to the first. Focus comes back to the number afterwards,
 * so the keyboard is where it was.
 */
export function CurrentPage({ page, pages, onGo, className }: { page: number; pages: number; onGo: (page: number) => void; className?: string }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const wasEditing = useRef(false)
  useEffect(() => {
    if (editing) {
      input.current?.focus()
      input.current?.select()
    } else if (wasEditing.current) {
      button.current?.focus()
    }
    wasEditing.current = editing
  }, [editing])

  if (!editing) {
    return (
      <Button
        ref={button}
        size="sm"
        variant="primary"
        aria-current="page"
        aria-label={`Page ${page} of ${pages}. Press to type a page number`}
        title="Press to type a page number"
        className={className}
        onClick={() => {
          setValue(String(page))
          setEditing(true)
        }}
      >
        {page}
      </Button>
    )
  }
  const go = () => {
    const wanted = Number.parseInt(value, 10)
    if (Number.isFinite(wanted)) onGo(Math.min(Math.max(wanted, 1), pages))
    setEditing(false)
  }
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        go()
      }}
    >
      <input
        ref={input}
        type="text"
        inputMode="numeric"
        aria-label={`Go to page, 1 to ${pages}`}
        value={value}
        onChange={(e) => setValue(e.target.value.replace(/\D/g, '').slice(0, 6))}
        onBlur={() => setEditing(false)}
        onKeyDown={(e) => {
          if (e.key === 'Escape') {
            e.stopPropagation()
            setEditing(false)
          }
        }}
        className="num h-8 w-14 rounded-md border border-ring bg-background px-1 text-center text-sm outline-none ring-2 ring-ring/40"
      />
    </form>
  )
}

/** "Page 5 of 12" with the number typeable, for a list that is paged by the server. */
export function PageJump({ page, pages, onGo }: { page: number; pages: number; onGo: (page: number) => void }) {
  return (
    <span className="num inline-flex items-center gap-2 text-muted-foreground" aria-live="polite">
      Page <CurrentPage page={page} pages={pages} onGo={onGo} /> of {pages}
    </span>
  )
}

/** The page numbers to offer: the first, the last, and the ones around this one, with a gap marked where some are left out. */
export function pageNumbers(page: number, pages: number): (number | '…')[] {
  const wanted = new Set([1, pages, page - 1, page, page + 1].filter((n) => n >= 1 && n <= pages))
  const sorted = [...wanted].sort((a, b) => a - b)
  const out: (number | '…')[] = []
  sorted.forEach((n, i) => {
    if (i > 0 && n - sorted[i - 1]! > 1) out.push('…')
    out.push(n)
  })
  return out
}

export function Pager({
  paged,
  label,
  scrollTo,
  className,
}: {
  paged: Pick<Paged<unknown>, 'page' | 'pages' | 'from' | 'to' | 'total' | 'paged' | 'setPage'>
  /** What the pages are of, for a screen reader ("Rows waiting"). */
  label: string
  /** The id of the element to bring back into view when the page turns, so the new page starts at its top. */
  scrollTo?: string
  className?: string
}) {
  if (!paged.paged) return null
  const go = (page: number) => {
    paged.setPage(page)
    if (scrollTo) requestAnimationFrame(() => document.getElementById(scrollTo)?.scrollIntoView?.({ block: 'start' }))
  }
  return (
    <nav aria-label={`${label}, pages`} className={className ?? 'flex flex-wrap items-center justify-between gap-3 border-t border-border-strong px-4 py-3 text-sm'}>
      <span className="num text-muted-foreground" aria-live="polite">
        Showing {paged.from}–{paged.to} of {paged.total}
      </span>
      <div className="flex flex-wrap items-center gap-1">
        <Button variant="outline" size="sm" disabled={paged.page <= 1} onClick={() => go(paged.page - 1)}>
          Previous
        </Button>
        {pageNumbers(paged.page, paged.pages).map((n, i) =>
          n === '…' ? (
            <span key={`gap-${i}`} aria-hidden className="px-1 text-muted-foreground">
              …
            </span>
          ) : n === paged.page ? (
            <CurrentPage key={n} page={paged.page} pages={paged.pages} onGo={go} />
          ) : (
            <Button key={n} size="sm" variant="ghost" aria-label={`Page ${n}`} onClick={() => go(n)}>
              {n}
            </Button>
          ),
        )}
        <Button variant="outline" size="sm" disabled={paged.page >= paged.pages} onClick={() => go(paged.page + 1)}>
          Next
        </Button>
      </div>
    </nav>
  )
}

/** A list that pages itself: for a place where the component cannot hold a hook (it returns early), or that is only a table. */
export function PagedList<T>({
  rows,
  resetKey,
  label,
  section,
  children,
}: {
  rows: readonly T[]
  resetKey: string
  label: string
  /** Which list this is, so the rows per page the person chose for it (Preferences) apply. */
  section: PageSection
  children: (items: T[]) => ReactNode
}) {
  const paged = usePaged(rows, resetKey, usePageSize(section))
  const body = useRef<HTMLDivElement>(null)
  useFadeOnChange(body, paged.page)
  return (
    <>
      <div ref={body}>{children(paged.items)}</div>
      <Pager paged={paged} label={label} className="flex flex-wrap items-center justify-between gap-3 pt-3 text-sm" />
    </>
  )
}
