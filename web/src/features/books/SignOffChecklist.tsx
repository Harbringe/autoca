// What stands between the books and a review: every check in its place, numbered 1, 2, 3. A check that passes turns its number
// into a tick; the next one that still fails is open; a line at the bottom counts how many have passed.
// Each check opens to its own reason and its own way to clear it (open Review, tick the assistant's entries,
// look at the bank difference), so there is one place to act per line and each fact is said once. Checks that
// pass fold into a single line.

import { Link } from '@tanstack/react-router'
import { Check, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import type { CloseReport, JournalEntry } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Reveal } from '@/components/ui/collapse'
import { Checkbox } from '@/components/ui/controls'
import { formatDate, plural } from '@/lib/format'
import { cn } from '@/lib/utils'
import { bankFigures, checkFigure, firstSentence, restAfterFirst } from './signOffChecks'

type CloseCheck = CloseReport['checks'][number]

/** The circle at the left of a check: its number while it fails, a tick once it passes. The two swap with a short fade. */
function Badge1({ ok, n }: { ok: boolean; n: number }) {
  return (
    <span
      aria-hidden
      className={cn(
        'grid size-7 place-items-center rounded-full text-[13px] font-semibold transition-colors duration-300',
        ok ? 'bg-success text-primary-foreground' : 'border-2 border-destructive text-destructive',
      )}
    >
      <span key={String(ok)} className="fade-in grid place-items-center">
        {ok ? <Check className="size-4" /> : n}
      </span>
    </span>
  )
}

function Figure({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return (
    <div className="rounded-lg border bg-card px-3 py-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn('num mt-0.5 text-[15px] font-semibold', bad ? 'text-destructive' : 'text-heading')}>{value}</dd>
    </div>
  )
}

export function SignOffChecklist({
  clientId,
  checks,
  entries,
  canMark,
  onMark,
  onMarkAll,
}: {
  clientId: string
  checks: CloseCheck[]
  /** Entries still carrying the assistant's marker, when the person may see the books. */
  entries: JournalEntry[]
  canMark: boolean
  /** Mark these entries as checked. */
  onMark: (ids: string[]) => Promise<void>
  /** Ask to mark every assistant entry as checked (the parent confirms). */
  onMarkAll: () => void
}) {
  const failing = checks.filter((c) => !c.ok)
  const passed = checks.filter((c) => c.ok)
  const current = failing[0]?.name ?? null
  // null: the current check is open; '': everything shut; otherwise the one the person chose.
  const [open, setOpen] = useState<string | null>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  // A long list is drawn a hundred at a time inside a scrolling box, so hundreds of entries neither push the page down nor slow it.
  const [shownCount, setShownCount] = useState(100)
  const bankFailing = failing.some((c) => c.name.startsWith('bank_'))

  async function markPicked() {
    setBusy(true)
    try {
      await onMark([...picked])
      setPicked(new Set())
    } finally {
      setBusy(false)
    }
  }

  function detail(c: CloseCheck) {
    if (c.name === 'rows_posted') {
      return (
        <>
          {restAfterFirst(c.detail) && <p>{restAfterFirst(c.detail)}</p>}
          {bankFailing && <p className="text-muted-foreground">Doing this first usually clears the bank difference too.</p>}
          <div>
            <Button asChild size="sm">
              <Link to="/clients/$clientId/review" params={{ clientId }} search={{ stage: 'all' }}>
                Open Review
              </Link>
            </Button>
          </div>
        </>
      )
    }
    if (c.name === 'assistant_entries_checked') {
      return (
        <>
          <p className="text-muted-foreground">Tick the ones you have looked at. Sealing waits until all are checked.</p>
          {entries.length > 0 && (
            <div className="overflow-hidden rounded-lg border bg-card">
              {canMark && (
                <label className="flex cursor-pointer items-center gap-3 border-b bg-surface-2 px-3 py-2 text-[13px] text-muted-foreground">
                  <Checkbox
                    aria-label="Select every entry"
                    checked={picked.size === entries.length}
                    onChange={(ev) => setPicked(ev.target.checked ? new Set(entries.map((e) => e.id)) : new Set())}
                  />
                  {picked.size > 0 ? `${picked.size} of ${plural(entries.length, 'entry', 'entries')} selected` : `Select all ${plural(entries.length, 'entry', 'entries')}`}
                </label>
              )}
              <ul className="max-h-80 divide-y overflow-y-auto overscroll-contain text-sm">
                {entries.slice(0, shownCount).map((e) => (
                  <li key={e.id} className="grid grid-cols-[auto_auto_minmax(0,1fr)_auto] items-center gap-3 px-3 py-2">
                    {canMark ? (
                      <Checkbox
                        aria-label={`Mark ${e.voucher_type} ${e.entry_no} as checked`}
                        checked={picked.has(e.id)}
                        onChange={(ev) =>
                          setPicked((prev) => {
                            const next = new Set(prev)
                            if (ev.target.checked) next.add(e.id)
                            else next.delete(e.id)
                            return next
                          })
                        }
                      />
                    ) : (
                      <span />
                    )}
                    <span className="num text-xs text-muted-foreground">{formatDate(e.entry_date)}</span>
                    <span className="min-w-0 truncate" title={e.narration}>
                      {e.voucher_type} · {e.entry_no}
                      <span className="text-muted-foreground"> {e.narration}</span>
                      {e.marker === 'AI_REVISED' && <span className="ml-2 text-xs text-accent-foreground">Changed after a correction</span>}
                    </span>
                    <span className="num">{e.total_display}</span>
                  </li>
                ))}
                {entries.length > shownCount && (
                  <li className="px-3 py-2 text-center">
                    <Button size="sm" variant="ghost" onClick={() => setShownCount((n) => n + 100)}>
                      Show 100 more ({entries.length - shownCount} left)
                    </Button>
                  </li>
                )}
              </ul>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            {canMark && (
              <>
                <Button size="sm" onClick={() => void markPicked()} loading={busy} disabled={picked.size === 0}>
                  Mark {picked.size > 0 ? picked.size : 'selected'} as checked
                </Button>
                <Button size="sm" variant="outline" onClick={onMarkAll}>
                  Mark all as checked
                </Button>
              </>
            )}
            <Button asChild size="sm" variant="ghost">
              <Link to="/clients/$clientId/daybook" params={{ clientId }}>
                Open in the Day Book
              </Link>
            </Button>
          </div>
        </>
      )
    }
    if (c.name.startsWith('bank_')) {
      const f = bankFigures(c.detail)
      return (
        <>
          {f ? (
            <>
              <dl className="grid max-w-xl grid-cols-3 gap-2">
                <Figure label="Books say" value={f.books} />
                <Figure label="Bank says" value={f.bank} />
                <Figure label="Difference" value={f.difference} bad />
              </dl>
              {f.unposted && (
                <p className="text-muted-foreground">
                  {f.unposted} {f.unposted === '1' ? 'transaction is' : 'transactions are'} not posted yet, the likeliest cause.
                </p>
              )}
            </>
          ) : (
            restAfterFirst(c.detail) && <p>{restAfterFirst(c.detail)}</p>
          )}
          <div>
            <Button asChild size="sm">
              <Link to="/clients/$clientId/statements" params={{ clientId }}>
                Open bank statements
              </Link>
            </Button>
          </div>
        </>
      )
    }
    return restAfterFirst(c.detail) ? <p>{restAfterFirst(c.detail)}</p> : null
  }

  return (
    <Card className="p-0" aria-labelledby="checks-heading">
      <h2 id="checks-heading" className="sr-only">
        Checks before the books are sent for review
      </h2>
      <ul className="divide-y">
        {checks.map((c, i) => {
          if (c.ok) {
            return (
              <li key={c.name} className="grid grid-cols-[1.75rem_minmax(0,1fr)_auto] items-center gap-3 px-5 py-3.5">
                <Badge1 ok n={i + 1} />
                <span className="min-w-0 truncate text-sm text-muted-foreground">{c.title}</span>
                <span className="text-sm font-medium text-success">Passed</span>
              </li>
            )
          }
          const isOpen = open === c.name || (open === null && current === c.name)
          const figure = checkFigure(c)
          return (
            <li key={c.name} className={cn('transition-colors duration-300', current === c.name && 'bg-surface-2')}>
              <button
                type="button"
                aria-expanded={isOpen}
                onClick={() => setOpen(isOpen ? '' : c.name)}
                className="grid w-full grid-cols-[1.75rem_minmax(0,1fr)_auto_1rem] items-center gap-3 px-5 py-3.5 text-left hover:bg-hover"
              >
                <Badge1 ok={false} n={i + 1} />
                <span className="min-w-0">
                  <span className="block font-semibold text-heading">{c.title}</span>
                  <span className="block text-[13px] text-muted-foreground">{firstSentence(c.detail)}</span>
                </span>
                <span className="num text-sm font-medium text-destructive">{figure}</span>
                <ChevronRight className={cn('size-4 text-muted-foreground transition-transform duration-200', isOpen && 'rotate-90')} aria-hidden />
              </button>
              <Reveal open={isOpen}>
                <div className="grid gap-3 px-5 pb-4 pl-[3.75rem] text-sm">{detail(c)}</div>
              </Reveal>
            </li>
          )
        })}
        <li className="flex items-center justify-between gap-3 bg-surface-2 px-5 py-3 text-sm" role="status">
          <span className="text-muted-foreground">
            <span className="num font-semibold text-heading">{passed.length}</span> of <span className="num">{checks.length}</span> {checks.length === 1 ? 'check' : 'checks'} passed
          </span>
          {failing.length === 0 && <span className="font-medium text-success">Ready to send</span>}
        </li>
      </ul>
    </Card>
  )
}
