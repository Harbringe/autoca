import { formatCompact, formatPaise } from '@/lib/format'
import { cn } from '@/lib/utils'
import { ChartTable } from './ChartTable'
import { segmentStyle } from './StackedBar'

export interface SignedRow {
  key: string
  label: string
  /** Whole paise; negative is drawn to the left of the zero line. */
  value: number
  /** A note after the label ("owed"). */
  note?: string
  /** What is written at the bar's end, when it should not be the signed compact figure ("₹5 L" for a loan owed). */
  display?: string
  /** The exact figure for the tooltip and hidden table, when `display` is given. */
  full?: string
  /** `watch` for money owed (not a fault, but not money in hand). Default: focus for positive, bad for negative. */
  tone?: 'watch'
}

/**
 * Balances from a zero line, sorted by size: positive to the right, negative to the left, so a bank account that is overdrawn
 * cannot look like money in hand. Bars start at zero and share one scale; the figure sits at the bar's end.
 */
export function SignedBars({ rows, ariaLabel, caption }: { rows: SignedRow[]; ariaLabel: string; caption: string }) {
  const max = Math.max(0, ...rows.map((r) => r.value))
  const min = Math.min(0, ...rows.map((r) => r.value))
  const span = Math.max(max - min, 1)
  const zero = (-min / span) * 100
  const sorted = [...rows].sort((a, b) => b.value - a.value)
  return (
    <div>
      <ul role="img" aria-label={ariaLabel} className="grid gap-2">
        {sorted.map((r) => {
          const w = (Math.abs(r.value) / span) * 100
          return (
            <li key={r.key} className="grid gap-1">
              <span className="flex items-baseline justify-between gap-3 text-sm">
                <span className="min-w-0 truncate text-muted-foreground" title={r.label}>
                  {r.label}
                  {r.note && <span className="ml-1 text-xs">({r.note})</span>}
                </span>
                <span className={cn('num shrink-0 font-medium', r.value < 0 && !r.tone ? 'text-destructive' : 'text-heading')} title={r.full ?? formatPaise(r.value)}>
                  {r.display ?? formatCompact(r.value)}
                </span>
              </span>
              <span className="relative block h-3 rounded-sm bg-muted/60" aria-hidden>
                <span className="absolute inset-y-0 w-px bg-[var(--faint)]" style={{ left: `${zero}%` }} />
                <span
                  className="absolute inset-y-0.5 rounded-sm"
                  style={{ ...segmentStyle(r.tone ?? (r.value < 0 ? 'bad' : 'focus')), width: `${Math.max(w, r.value === 0 ? 0 : 0.8)}%`, left: r.value < 0 ? `${zero - w}%` : `${zero}%` }}
                />
              </span>
            </li>
          )
        })}
      </ul>
      <ChartTable caption={caption} columns={['Account', 'Balance']} rows={sorted.map((r) => [r.label + (r.note ? ` (${r.note})` : ''), r.full ?? formatPaise(r.value)])} />
    </div>
  )
}
