// How far a firm's move from Tally has got: the steps, and for each financial year how many monthly imports are waiting, being
// posted, or posted. Built from the import queue alone, so it needs nothing the queue does not already say.

import type { VoucherRunSummary } from '@/api/queries/tallyImport'
import { Card } from '@/components/ui/card'

/** The financial year (its starting year) a date falls in: April to March. */
function yearOf(isoDate: string): number {
  const [year, month] = isoDate.split('-').map(Number)
  return (month ?? 4) >= 4 ? (year ?? 0) : (year ?? 0) - 1
}

const label = (start: number) => `FY ${start}-${String((start + 1) % 100).padStart(2, '0')}`

export function MoveProgress({ runs }: { runs: VoucherRunSummary[] }) {
  const years = new Map<number, { waiting: number; posting: number; posted: number }>()
  for (const run of runs) {
    if (run.status === 'DISCARDED') continue
    const year = yearOf(run.counts.date_from)
    const row = years.get(year) ?? { waiting: 0, posting: 0, posted: 0 }
    if (run.status === 'CONFIRMED') row.posted += 1
    else if (run.posting) row.posting += 1
    else row.waiting += 1
    years.set(year, row)
  }
  const ordered = [...years.entries()].sort((a, b) => b[0] - a[0])

  return (
    <Card className="grid gap-2 p-4 text-sm" data-testid="move-progress">
      <h2 className="font-medium">Moving from Tally</h2>
      <ol className="list-decimal pl-5 text-muted-foreground">
        <li>Bring in the ledger list first (above), so each ledger is under the right group.</li>
        <li>Optionally, Tally's voucher types file, if the firm made voucher types of its own.</li>
        <li>Then the vouchers, a year or more at a time. A large file is cut into one import per month.</li>
      </ol>
      {ordered.length === 0 ? (
        <p className="text-muted-foreground">Nothing has been read yet.</p>
      ) : (
        <ul aria-label="Imports by financial year" className="divide-y divide-border-strong rounded-lg border border-border-strong">
          {ordered.map(([year, row]) => (
            <li key={year} data-testid={`fy-${year}`} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <span className="font-medium">{label(year)}</span>
              <span className="text-muted-foreground">
                {[row.waiting && `${row.waiting} waiting`, row.posting && `${row.posting} posting`, row.posted && `${row.posted} posted`]
                  .filter(Boolean)
                  .join(' · ')}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
