// Small readings the Clients list needs: the tile letters, how wide a waiting bar is, and the count on each
// filter pill. Pure, so they are tested.

/** Up to two capital letters from the first two words of a name: "Gajanan Cloth Center" gives "GC". */
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return '?'
  return words
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join('')
}

/** A bar's width as a whole percent of the busiest client; any non-zero count stays visible. */
export function barPercent(count: number, max: number): number {
  if (count <= 0 || max <= 0) return 0
  return Math.min(100, Math.max(4, Math.round((count / max) * 100)))
}

export interface CountRow {
  unresolved: number
  ready: number
  mine: boolean
  assigned: boolean
}

export interface FilterCounts {
  all: number
  mine: number
  unresolved: number
  ready: number
  unassigned: number
}

/** What each filter pill would show for these rows. */
export function filterCounts(rows: CountRow[]): FilterCounts {
  return {
    all: rows.length,
    mine: rows.filter((r) => r.mine).length,
    unresolved: rows.filter((r) => r.unresolved > 0).length,
    ready: rows.filter((r) => r.ready > 0).length,
    unassigned: rows.filter((r) => !r.assigned).length,
  }
}
