import { Link } from '@tanstack/react-router'
import { pct } from '@/lib/pct'
import { cn } from '@/lib/utils'

export interface RankedRow {
  key: string
  label: string
  /** Bar length. A count or an amount in paise; never a display string. */
  value: number
  /** What is written at the end of the row. */
  valueLabel: string
  /** Why, in words, under the label (so the bar is never the only reason). */
  note?: string
  to?: string
  params?: Record<string, string>
  search?: Record<string, unknown>
  tone?: 'primary' | 'accent' | 'danger'
}

const FILL = { primary: 'bg-primary', accent: 'bg-accent-foreground', danger: 'bg-destructive' } as const

/**
 * Rows with an inline bar. Plain HTML, not a chart library: text wraps, rows are links, it prints,
 * and the words are the data, so there is nothing to describe separately. Used for clients and
 * expense heads, never to rank people.
 */
export function RankedBars({ rows, max, className }: { rows: RankedRow[]; max?: number; className?: string }) {
  const top = max ?? Math.max(...rows.map((r) => r.value), 1)
  return (
    <ul className={cn('grid gap-1', className)}>
      {rows.map((r) => {
        const body = (
          <>
            <span className="flex items-baseline justify-between gap-3">
              <span className="min-w-0 truncate text-sm font-medium text-heading" title={r.label}>
                {r.label}
              </span>
              <span className={cn('num shrink-0 text-sm', r.tone === 'danger' ? 'font-semibold text-destructive' : 'text-heading')}>{r.valueLabel}</span>
            </span>
            <span className="block h-2 overflow-hidden rounded-full bg-muted" aria-hidden>
              <span className={cn('block h-full rounded-full', FILL[r.tone ?? 'primary'])} style={{ width: `${r.value > 0 ? Math.max(pct(r.value, top), 2) : 0}%` }} />
            </span>
            {r.note && <span className="block text-xs text-muted-foreground">{r.note}</span>}
          </>
        )
        const box = 'grid min-h-11 content-center gap-1 rounded-md px-2 py-1.5 -mx-2'
        return (
          <li key={r.key}>
            {r.to ? (
              <Link to={r.to as never} params={r.params as never} search={r.search as never} className={cn(box, 'hover:bg-hover')}>
                {body}
              </Link>
            ) : (
              <div className={box}>{body}</div>
            )}
          </li>
        )
      })}
    </ul>
  )
}
