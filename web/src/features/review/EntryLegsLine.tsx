// The two sides of the entry a placed row makes, shown in the list without opening the row, the way Tally's ledger vouchers show them:
// which ledger is debited and which credited, and for how much. An unplaced row has no other side yet, so it shows nothing.

import type { EntryLeg } from '@/api/types'

export function EntryLegsLine({ legs }: { legs: EntryLeg[] | undefined }) {
  const placed = (legs ?? []).filter((leg) => leg.ledger)
  if (placed.length < 2) return null
  return (
    <span role="group" aria-label="The entry this makes" className="mt-1 grid gap-px font-mono text-xs text-muted-foreground">
      {placed.map((leg, i) => (
        <span key={`${leg.side}-${i}`} className="flex min-w-0 items-baseline gap-2">
          <span className="w-5 shrink-0 font-semibold text-faint">{leg.side}</span>
          <span className="min-w-0 truncate" title={leg.ledger ?? undefined}>
            {leg.ledger}
          </span>
          <span className="num ml-auto shrink-0">{leg.amount_display}</span>
        </span>
      ))}
    </span>
  )
}
