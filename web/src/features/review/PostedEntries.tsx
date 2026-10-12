// Everything already posted for a client, in every financial year: the entries the books are made
// of. The other review tabs are the work still waiting; this one is the work that has been done.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useMemo, useState } from 'react'
import { journal } from '@/api/queries/books'
import type { JournalEntry } from '@/api/types'
import { Money } from '@/components/ca/Money'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Select } from '@/components/ui/controls'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { Button } from '@/components/ui/button'
import { Collapse, useClosing } from '@/components/ui/collapse'
import { formatDate, plural } from '@/lib/format'
import { cn } from '@/lib/utils'
import { StageNav, STAGES } from './StageNav'

/** The ledgers on each side of an entry, as one comma-separated string per side. */
export function particulars(entry: JournalEntry): { debit: string; credit: string } {
  const names = (side: 'DR' | 'CR') => [...new Set(entry.lines.filter((l) => l.direction === side).map((l) => l.ledger_name))].join(', ')
  return { debit: names('DR'), credit: names('CR') }
}

export function PostedEntries({ clientId }: { clientId: string }) {
  const entries = useQuery(journal(clientId))
  const [year, setYear] = useState('')
  const [text, setText] = useState('')
  const [openId, setOpenId] = useState<string | null>(null)
  const closing = useClosing(openId)

  const years = useMemo(() => {
    const seen = new Map<number, string>()
    for (const e of entries.data ?? []) seen.set(e.financial_year, e.fy_label)
    return [...seen.entries()].sort((a, b) => b[0] - a[0])
  }, [entries.data])

  const q = text.trim().toLowerCase()
  const rows = useMemo(
    () =>
      (entries.data ?? [])
        .filter((e) => !year || String(e.financial_year) === year)
        .filter((e) => {
          if (!q) return true
          const { debit, credit } = particulars(e)
          return [e.narration, debit, credit, `${e.voucher_type} ${e.entry_no}`].some((v) => v.toLowerCase().includes(q))
        })
        .sort((a, b) => b.entry_date.localeCompare(a.entry_date) || b.entry_no - a.entry_no),
    [entries.data, year, q],
  )

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <StageNav clientId={clientId} active="posted" />
      </div>
      <p className="text-sm text-muted-foreground">{STAGES.find((s) => s.stage === 'posted')?.hint}</p>

      {entries.isPending ? (
        <Spinner />
      ) : entries.error ? (
        <ErrorState error={entries.error} retry={() => void entries.refetch()} />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <Input
              aria-label="Search posted entries"
              className="max-w-sm"
              placeholder="Search narration, ledger or voucher number"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <Select aria-label="Financial year" className="w-auto" value={year} onChange={(e) => setYear(e.target.value)}>
              <option value="">All years</option>
              {years.map(([fy, label]) => (
                <option key={fy} value={fy}>
                  FY {label}
                </option>
              ))}
            </Select>
            <span className="text-sm text-muted-foreground">{plural(rows.length, 'entry', 'entries')}</span>
          </div>
          {rows.length === 0 ? (
            <EmptyState title={q || year ? 'No posted entries match' : 'Nothing has been posted yet'}>
              {q || year ? (
                'Try another year or a different search.'
              ) : (
                <>
                  Rows placed in a ledger appear here once they are posted from{' '}
                  <Link to="/clients/$clientId/review" params={{ clientId }} search={{ stage: 'pending_approval' }} className="underline">
                    Ready to post
                  </Link>
                  .
                </>
              )}
            </EmptyState>
          ) : (
            <div className="overflow-hidden rounded-xl border border-border-strong bg-surface-2">
              <ul aria-label="Posted entries, newest first" className="divide-y divide-border-strong">
                {rows.map((e) => {
                  const isOpen = e.id === openId
                  const showBody = isOpen || closing === e.id
                  const { debit, credit } = particulars(e)
                  return (
                    <li
                      key={e.id}
                          className={cn('relative transition-colors duration-200', isOpen ? 'bg-hover shadow-[inset_3px_0_0_var(--primary)]' : 'hover:bg-hover/60')}
                    >
                      <button
                        type="button"
                        aria-expanded={isOpen}
                        aria-controls={`entry-${e.id}`}
                        onClick={() => setOpenId(isOpen ? null : e.id)}
                        className="grid w-full grid-cols-[6rem_minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 px-5 py-4 text-left max-sm:grid-cols-[minmax(0,1fr)_auto]"
                      >
                        <span className="num font-mono text-[13px] text-muted-foreground max-sm:col-span-2">{formatDate(e.entry_date)}</span>
                        <span className="min-w-0">
                          <span className="block truncate" title={e.narration}>
                            <span className="font-mono text-xs text-muted-foreground">{e.narration}</span>
                            {e.marker_display && <Badge className="ml-2">{e.marker_display}</Badge>}
                          </span>
                          <span className="mt-0.5 block truncate text-[13px] text-muted-foreground">
                            {e.voucher_type} · {e.entry_no} · FY {e.fy_label}
                          </span>
                        </span>
                        <span className="num text-right font-mono text-heading">
                          <Money display={e.total_display} />
                        </span>
                      </button>
                      {showBody && (
                        <div id={`entry-${e.id}`}>
                          <Collapse open={isOpen}>
                            <div className="grid gap-4 px-5 pb-5 pt-1">
                              <div>
                                <div className="mb-1.5 text-[13px] text-muted-foreground">The entry</div>
                                <div className="divide-y divide-border-strong rounded-lg border border-border-strong px-4 text-sm">
                                  {e.lines.map((l) => (
                                    <div key={l.id} className="flex items-center justify-between gap-3 py-2.5">
                                      <span>
                                        <em className="mr-1.5 not-italic text-muted-foreground">{l.direction === 'DR' ? 'Dr' : 'Cr'}</em>
                                        {l.ledger_name}
                                      </span>
                                      <span className="num">
                                        <Money display={l.amount_display} />
                                      </span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                              <p className="text-sm text-muted-foreground">
                                This entry is in the books ({debit} to {credit}). Until they are signed off you can still correct or remove it in the Day Book.
                              </p>
                              <div>
                                <Button asChild variant="outline" className="rounded-lg dark:border-border-strong dark:bg-background">
                                  <Link to="/clients/$clientId/daybook" params={{ clientId }}>
                                    Open in Day Book
                                  </Link>
                                </Button>
                              </div>
                            </div>
                          </Collapse>
                        </div>
                      )}
                    </li>
                  )
                })}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  )
}
