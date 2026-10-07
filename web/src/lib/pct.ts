// Percentages for legends and progress bars, from integer counts, with one rounding rule so a
// column of percentages always adds up to 100. Largest remainder: every row gets the floor of its
// exact share, then the leftover points go to the rows with the biggest fractional parts (ties go
// to the earlier row, so the result never depends on sort stability).

/** Whole percentages of `counts`, in the same order, summing to 100 (all zeros when the total is 0). */
export function percentages(counts: number[]): number[] {
  const total = counts.reduce((sum, n) => sum + Math.max(n, 0), 0)
  if (total <= 0) return counts.map(() => 0)
  const exact = counts.map((n) => (Math.max(n, 0) * 100) / total)
  const floors = exact.map(Math.floor)
  let left = 100 - floors.reduce((sum, n) => sum + n, 0)
  const order = exact
    .map((value, index) => ({ index, rest: value - Math.floor(value) }))
    .sort((a, b) => b.rest - a.rest || a.index - b.index)
  for (const { index } of order) {
    if (left <= 0) break
    floors[index]! += 1
    left -= 1
  }
  return floors
}

/** One whole percentage: `part` of `whole`, rounded to nearest; 0 when there is no whole. */
export function pct(part: number, whole: number): number {
  return whole > 0 ? Math.round((Math.max(part, 0) * 100) / whole) : 0
}
