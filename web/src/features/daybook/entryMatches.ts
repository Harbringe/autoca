// Does a Day Book entry match what was typed in the search box? Narration, any line's ledger or party, or the number it had in Tally.

interface Searchable {
  narration: string
  tally_number?: string | null
  lines: { ledger_name: string; party_name?: string | null }[]
}

export function entryMatches(entry: Searchable, text: string): boolean {
  const q = text.trim().toLowerCase()
  if (!q) return true
  return (
    entry.narration.toLowerCase().includes(q) ||
    (entry.tally_number ?? '').toLowerCase().includes(q) ||
    entry.lines.some((l) => l.ledger_name.toLowerCase().includes(q) || (l.party_name ?? '').toLowerCase().includes(q))
  )
}
