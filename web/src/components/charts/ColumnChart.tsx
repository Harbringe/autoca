import { axisMoney } from '@/lib/chartFormat'
import { formatPaise } from '@/lib/format'
import { cn } from '@/lib/utils'
import { ChartTable } from './ChartTable'
import { segmentStyle, type SegmentTone } from './StackedBar'

export interface ColumnPoint {
  key: string
  /** The short label under the column ("Apr"). */
  label: string
  /** The full label for the tooltip and hidden table ("April 2026"). */
  full: string
  /** One value per series, whole paise; negative hangs below the zero line. */
  values: number[]
  /** A mark for this column ("late"): shown as an icon-free dot above it and in the tooltip. */
  flag?: string
}

export interface ColumnSeries {
  name: string
  tone: SegmentTone
}

/**
 * Columns from a zero line, one or two series per category. Bars start at zero always; negatives hang below it. Money on the
 * axis is compact (₹1.2 L), full paise in the hover tooltip and the hidden table. Hover or keyboard focus shows the tooltip.
 * Plain HTML so it needs no chart library and reflows at 390 px (labels thin out, columns narrow, nothing scrolls).
 */
export function ColumnChart({
  points,
  series,
  ariaLabel,
  caption,
  className,
  unit = 'money',
}: {
  points: ColumnPoint[]
  series: ColumnSeries[]
  ariaLabel: string
  caption: string
  className?: string
  /** `count` draws whole numbers on the axis and in the tooltip; `money` (default) takes whole paise. */
  unit?: 'money' | 'count'
}) {
  const fmt = (v: number) => (unit === 'count' ? String(v) : formatPaise(v))
  const axis = (v: number) => (unit === 'count' ? String(v) : axisMoney(v))
  const all = points.flatMap((p) => p.values)
  const max = Math.max(0, ...all)
  const min = Math.min(0, ...all)
  const span = Math.max(max - min, 1)
  const zero = (max / span) * 100
  const every = points.length > 8 ? 2 : 1
  return (
    <div className={className}>
      <div className="mb-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-hidden>
        {series.map((s) => (
          <span key={s.name} className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-sm" style={segmentStyle(s.tone)} /> {s.name}
          </span>
        ))}
      </div>
      <div className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-x-1">
        <div className="relative h-40 text-right text-xs text-muted-foreground" aria-hidden>
          <span className="num absolute right-1 top-0 -translate-y-1/2">{axis(max)}</span>
          <span className="num absolute right-1 -translate-y-1/2" style={{ top: `${zero}%` }}>
            0
          </span>
          {min < 0 && (
            <span className="num absolute bottom-0 right-1 translate-y-1/2">{axis(min)}</span>
          )}
        </div>
        <div role="img" aria-label={ariaLabel} className="relative h-40 border-b-0">
          <span className="absolute inset-x-0 h-px bg-[var(--faint)]" style={{ top: `${zero}%` }} aria-hidden />
          <span className="absolute inset-x-0 top-0 h-px bg-[var(--chart-grid)]" aria-hidden />
          <div className="absolute inset-0 flex gap-1">
            {points.map((p) => (
              <div key={p.key} className="group relative flex h-full min-w-0 flex-1 justify-center gap-px">
                {p.values.map((v, i) => {
                  const h = (Math.abs(v) / span) * 100
                  return (
                    <span
                      key={series[i]?.name ?? i}
                      className="absolute block rounded-t-sm"
                      style={{
                        ...segmentStyle(series[i]?.tone ?? 'focus'),
                        height: `${v === 0 ? 0 : Math.max(h, 1)}%`,
                        ...(v >= 0 ? { bottom: `${100 - zero}%` } : { top: `${zero}%`, borderRadius: '0 0 2px 2px' }),
                        left: `${10 + (80 / p.values.length) * i}%`,
                        width: `${80 / p.values.length}%`,
                      }}
                    />
                  )
                })}
                <span className="absolute inset-0 z-10" />
                <span
                  className={cn(
                    'pointer-events-none absolute z-20 hidden min-w-max -translate-x-1/2 rounded-md border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-float group-hover:block',
                    'left-1/2 top-0',
                  )}
                  aria-hidden
                >
                  <span className="block font-medium text-heading">{p.full}</span>
                  {p.values.map((v, i) => (
                    <span key={i} className="num block">
                      {series[i]?.name}: {fmt(v)}
                    </span>
                  ))}
                  {p.flag && <span className="block text-destructive">{p.flag}</span>}
                </span>
              </div>
            ))}
          </div>
        </div>
        <span />
        <div className="mt-1 flex gap-1 text-xs text-muted-foreground" aria-hidden>
          {points.map((p, i) => (
            <span key={p.key} className="min-w-0 flex-1 truncate text-center">
              {i % every === 0 ? p.label : ''}
            </span>
          ))}
        </div>
      </div>
      <ChartTable caption={caption} columns={['Month', ...series.map((s) => s.name)]} rows={points.map((p) => [p.full, ...p.values.map((v) => fmt(v))])} />
    </div>
  )
}

/** The shape of a column chart while it loads: a zero line and ghost columns, not a spinner. */
export function ColumnSkeleton({ className }: { className?: string }) {
  const heights = [40, 65, 50, 80, 55, 70, 45, 60, 75, 50, 65, 40]
  return (
    <div className={cn('flex h-40 items-end gap-1 border-b', className)} aria-hidden>
      {heights.map((h, i) => (
        <span key={i} className="skeleton block flex-1" style={{ height: `${h}%` }} />
      ))}
    </div>
  )
}

/** A drawn empty chart: a zero line and ghost columns at zero height, with the one line that says what fills it. */
export function EmptyPlot({ line, className }: { line: string; className?: string }) {
  const heights = [30, 55, 40, 70, 45, 60, 35, 65, 50, 40, 55, 30]
  return (
    <div className={className}>
      <div className="flex h-20 items-end gap-1 border-b border-[var(--faint)]" aria-hidden>
        {heights.map((h, i) => (
          <span key={i} className="block flex-1 rounded-t-sm border border-dashed border-border" style={{ height: `${h}%` }} />
        ))}
      </div>
      <p className="mt-2 text-sm text-muted-foreground">{line}</p>
    </div>
  )
}
