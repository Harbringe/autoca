// Tally's bank ledger view, for the Review list. A row's amount sits in the Debit column when the bank account is debited (money in) and in
// the Credit column when it is credited (money out); the ledger on the other side is the row's Particulars. An entry with more than one other
// ledger (a split) is "(as per details)" in Tally, and here lists each of its legs under the row.

import type { EntryLeg } from '@/api/types'

/** Which side of the entry the bank account is on: that is the column the amount goes in. */
export function bankSideOf(row: { entry_legs?: EntryLeg[]; transaction: { is_debit: boolean } }): 'Dr' | 'Cr' {
  return row.entry_legs?.find((leg) => leg.is_bank)?.side ?? (row.transaction.is_debit ? 'Cr' : 'Dr')
}

export function EntryLegsLine({ legs }: { legs: EntryLeg[] | undefined }) {
  const others = (legs ?? []).filter((leg) => !leg.is_bank && leg.ledger)
  if (others.length < 2) return null
  return (
    <span role="group" aria-label="The entry this makes, as per details" className="mt-1 grid gap-px font-mono text-xs text-muted-foreground">
      <span className="text-faint">(as per details)</span>
      {others.map((leg, i) => (
        <span key={`${leg.side}-${i}`} className="flex min-w-0 items-baseline gap-2 pl-3">
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
