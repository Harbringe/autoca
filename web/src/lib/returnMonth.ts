// The month a return working opens on: the month just ended, the one a return is usually being prepared for, kept inside the financial year on screen.
// With a year that has not started it is April; with one that has finished it is March.

export function defaultReturnMonth(fy: number, now: Date = new Date()): string {
  const previous = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  const first = new Date(fy, 3, 1)
  const last = new Date(fy + 1, 2, 1)
  const chosen = previous < first ? first : previous > last ? last : previous
  return `${chosen.getFullYear()}-${String(chosen.getMonth() + 1).padStart(2, '0')}`
}

/** The calendar year and month (1 to 12) just ended, for a screen that takes them apart. */
export function previousMonth(now: Date = new Date()): { year: number; month: number } {
  const p = new Date(now.getFullYear(), now.getMonth() - 1, 1)
  return { year: p.getFullYear(), month: p.getMonth() + 1 }
}
