import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { ChartTable } from './ChartTable'
import { segmentStyle, type SegmentTone } from './StackedBar'

export interface RowPart {
  name: string
  value: number
  tone: SegmentTone
  /** What this part is written as in the tooltip and table (full figure). */
  full?: string
}

export interface StackedRow {
  key: string
  label: string
  /** A small mark after the label ("2 late"). */
  badge?: ReactNode
  parts: RowPart[]
  /** The row's total, written at the end of its bar. */
  totalLabel: string
  to?: string
  params?: Record<string, string>
  search?: Record<string, unknown>
}

/**
 * One bar per row, each split into parts, all on one scale so a longer bar is more. Used where a name has several kinds of
 * thing: a person's finished/open/waiting, a client's work by kind, a party's bills by age. Direct end labels, a swatch key
 * once (parts are named in the tooltip and the hidden table), links where a row has somewhere to go.
 */
export function StackedRows({
  rows,
  ariaLabel,
  caption,
  total = 'Total',
  className,
}: {
  rows: StackedRow[]
  ariaLabel: string
  caption: string
  total?: string
  className?: string
}) {
  const top = Math.max(1, ...rows.map((r) => r.parts.reduce((n, p) => n + Math.max(p.value, 0), 0)))
  const names = rows[0]?.parts.map((p) => ({ name: p.name, tone: p.tone })) ?? []
  return (
    <div className={className}>
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-hidden>
        {names.map((n) => (
          <span key={n.name} className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-sm" style={segmentStyle(n.tone)} /> {n.name}
          </span>
        ))}
      </div>
      <ul role="img" aria-label={ariaLabel} className="grid gap-1">
        {rows.map((r) => {
          const sum = r.parts.reduce((n, p) => n + Math.max(p.value, 0), 0)
          const body = (
            <>
              <span className="flex min-w-0 items-center gap-2 text-sm font-medium text-heading" title={r.label}>
                <span className="truncate">{r.label}</span>
                {r.badge}
              </span>
              <span className="flex h-3 min-w-0 gap-px overflow-hidden rounded-sm bg-muted" aria-hidden>
                {sum > 0 &&
                  r.parts.map((p) =>
                    p.value > 0 ? (
                      <span
                        key={p.name}
                        title={`${p.name}: ${p.full ?? p.value}`}
                        className="block h-full"
                        style={{ ...segmentStyle(p.tone), width: `${(p.value / top) * 100}%` }}
                      />
                    ) : null,
                  )}
              </span>
              <span className="num text-right text-sm text-heading">{r.totalLabel}</span>
            </>
          )
          const box = 'grid min-h-11 items-center gap-x-3 gap-y-1 rounded-md px-2 -mx-2 py-1 sm:grid-cols-[minmax(0,11rem)_minmax(0,1fr)_5rem]'
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
      <ChartTable
        caption={caption}
        columns={['Name', ...names.map((n) => n.name), total]}
        rows={rows.map((r) => [r.label, ...r.parts.map((p) => p.full ?? p.value), r.totalLabel])}
      />
    </div>
  )
}

/** Rows of ghost bars while loading. */
export function RowsSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="grid gap-2" aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="grid items-center gap-3 sm:grid-cols-[11rem_minmax(0,1fr)_5rem]">
          <span className="skeleton h-4 rounded" />
          <span className="skeleton h-3 rounded" style={{ width: `${90 - i * 18}%` }} />
          <span className="skeleton h-4 rounded" />
        </div>
      ))}
    </div>
  )
}
