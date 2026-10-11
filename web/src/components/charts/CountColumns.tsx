import { Link } from '@tanstack/react-router'
import { cn } from '@/lib/utils'
import { ChartTable } from './ChartTable'
import { segmentStyle, type SegmentTone } from './StackedBar'

export interface ColumnPart {
  name: string
  value: number
  tone: SegmentTone
}

export interface CountColumn {
  key: string
  label: string
  parts: ColumnPart[]
  to?: string
  params?: Record<string, string>
  search?: Record<string, unknown>
}

/**
 * Counts as upright columns, one per name, split into kinds, all from zero on one scale. The total sits on top of each
 * column and the name under it (direct labels). Columns are links where the count has a screen. At 390 px the columns narrow
 * and the names are shortened; the hidden table has every figure in full.
 */
export function CountColumns({ columns, ariaLabel, caption, unit = 'entries' }: { columns: CountColumn[]; ariaLabel: string; caption: string; unit?: string }) {
  const totals = columns.map((c) => c.parts.reduce((n, p) => n + Math.max(p.value, 0), 0))
  const top = Math.max(1, ...totals)
  const kinds = columns[0]?.parts ?? []
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-hidden>
        {kinds.map((k) => (
          <span key={k.name} className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-sm" style={segmentStyle(k.tone)} /> {k.name}
          </span>
        ))}
      </div>
      <ul role="img" aria-label={ariaLabel} className="flex h-48 items-end gap-2 border-b border-[var(--faint)] sm:gap-6">
        {columns.map((c, i) => {
          const body = (
            <>
              <span className="num mb-1 block text-center text-sm font-semibold text-heading">{totals[i]}</span>
              <span className="flex w-full flex-col-reverse overflow-hidden rounded-t-md" style={{ height: `${(totals[i]! / top) * 9}rem` }} aria-hidden>
                {c.parts.map((p) =>
                  p.value > 0 ? (
                    <span key={p.name} title={`${c.label}, ${p.name}: ${p.value} ${unit}`} className="block w-full" style={{ ...segmentStyle(p.tone), height: `${(p.value / Math.max(totals[i]!, 1)) * 100}%` }} />
                  ) : null,
                )}
              </span>
            </>
          )
          const col = 'flex h-full min-w-0 max-w-32 flex-1 flex-col justify-end'
          return (
            <li key={c.key} className={col}>
              {c.to && totals[i]! > 0 ? (
                <Link to={c.to as never} params={c.params as never} search={c.search as never} className={cn(col, 'rounded-t-md hover:bg-hover')}>
                  {body}
                </Link>
              ) : (
                <div className={col}>{body}</div>
              )}
            </li>
          )
        })}
      </ul>
      <ul className="mt-1.5 flex gap-2 sm:gap-6" aria-hidden>
        {columns.map((c) => (
          <li key={c.key} className="min-w-0 max-w-32 flex-1 truncate text-center text-xs text-muted-foreground" title={c.label}>
            {c.label}
          </li>
        ))}
      </ul>
      <ChartTable caption={caption} columns={['Name', ...kinds.map((k) => k.name), 'Total']} rows={columns.map((c, i) => [c.label, ...c.parts.map((p) => p.value), totals[i]!])} />
    </div>
  )
}

/** Ghost columns while loading. */
export function ColumnsSkeleton() {
  const h = [70, 100, 55, 85, 40, 65]
  return (
    <div className="flex h-48 items-end gap-4 border-b" aria-hidden>
      {h.map((v, i) => (
        <span key={i} className="skeleton block flex-1 rounded-t-md" style={{ height: `${v}%` }} />
      ))}
    </div>
  )
}
