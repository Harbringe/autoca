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
import { DataTable, type Column } from '@/components/ui/table'
import { formatDate, plural } from '@/lib/format'
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

  const columns: Column<JournalEntry>[] = [
    { key: 'date', header: 'Date', align: 'right', cell: (e) => formatDate(e.entry_date) },
    { key: 'vch', header: 'Voucher', priority: 2, cell: (e) => `${e.voucher_type} · ${e.entry_no}` },
    { key: 'fy', header: 'Year', priority: 3, cell: (e) => `FY ${e.fy_label}` },
    {
      key: 'narr',
      header: 'Narration',
      className: 'max-w-0 w-full truncate',
      cell: (e) => (
        <span title={e.narration}>
          {e.narration}
          {e.marker_display && <Badge className="ml-2">{e.marker_display}</Badge>}
        </span>
      ),
    },
    {
      key: 'sides',
      header: 'Debit / Credit ledger',
      priority: 2,
      cell: (e) => {
        const { debit, credit } = particulars(e)
        return (
          <span className="text-muted-foreground">
            Dr {debit} · Cr {credit}
          </span>
        )
      },
    },
    { key: 'amount', header: 'Amount', align: 'right', cell: (e) => <Money display={e.total_display} /> },
  ]

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
            <DataTable caption="Posted entries, newest first" rows={rows} rowKey={(e) => e.id} columns={columns} />
          )}
        </>
      )}
    </div>
  )
}
