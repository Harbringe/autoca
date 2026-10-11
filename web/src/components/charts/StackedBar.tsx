import { Link } from '@tanstack/react-router'
import type { CSSProperties } from 'react'
import { percentages } from '@/lib/pct'
import { cn } from '@/lib/utils'
import { ChartTable } from './ChartTable'

/**
 * `part1`..`part4` are the composition ramp (largest part darkest), `out` is money out, `context` is "everything else".
 * What a segment means, by name, so no screen picks a colour of its own. `age1`..`age3` are the ageing ramp
 * (lightest is newest); `bad` is hatched as well as red, so it survives greyscale and colour blindness.
 */
export type SegmentTone = 'focus' | 'context' | 'out' | 'age1' | 'age2' | 'age3' | 'watch' | 'good' | 'bad' | 'part1' | 'part2' | 'part3' | 'part4'

export interface BarSegment {
  key: string
  label: string
  /** Whole units (paise or a count), never negative. Drives the width. */
  value: number
  /** What is written beside the label: "₹1.2 L", "14". */
  valueLabel: string
  /** The exact figure for the hidden table and tooltip, when `valueLabel` is shortened. */
  fullLabel?: string
  tone: SegmentTone
  to?: string
  params?: Record<string, string>
  search?: Record<string, unknown>
}

const FILL: Record<SegmentTone, string> = {
  focus: 'var(--chart-1)',
  context: 'var(--chart-muted)',
  out: 'var(--chart-2)',
  part1: 'var(--chart-seq-1)',
  part2: 'var(--chart-seq-2)',
  part3: 'var(--chart-seq-3)',
  part4: 'var(--chart-seq-4)',
  age1: 'var(--chart-seq-4)',
  age2: 'var(--chart-seq-3)',
  age3: 'var(--chart-seq-2)',
  watch: 'var(--accent-foreground)',
  good: 'var(--success)',
  bad: 'var(--destructive)',
}

const HATCH = 'repeating-linear-gradient(135deg, transparent 0 5px, color-mix(in oklab, var(--card) 60%, transparent) 5px 7px)'

/**
 * The swatch or segment paint: a flat fill, hatched for the bad meaning, outlined in `--faint`. The outline matters:
 * the lightest ramp steps and the neutral fill are under 3:1 against the card in both themes (measured), so the shape
 * is carried by the edge and the meaning by the label under it, never by the tint alone.
 */
export function segmentStyle(tone: SegmentTone): CSSProperties {
  return { backgroundColor: FILL[tone], backgroundImage: tone === 'bad' ? HATCH : undefined, boxShadow: 'inset 0 0 0 1px var(--faint)' }
}

/** A drawn empty bar of the same shape, for loading. Not a spinner. */
export function StackedBarSkeleton({ rows = 1, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn('grid gap-4', className)} aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="grid gap-2">
          <div className="skeleton h-3 w-24 rounded" />
          <div className="skeleton h-7 w-full rounded-md" />
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {Array.from({ length: 4 }, (_, j) => (
              <div key={j} className="skeleton h-9 rounded" />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

/**
 * One horizontal bar split into labelled parts: how old money is, how a total divides. Plain HTML, so the labels wrap and
 * every part can be a link. Every part is named under the bar with its amount and share (direct labels, no legend to decode),
 * and the same data is in a hidden table. `scaleMax` lets several bars share one scale: a bar of half the scale fills half.
 * With nothing in it the bar is drawn empty and `empty` says what fills it. One part fills the whole bar and still reads.
 */
export function StackedBar({
  segments,
  ariaLabel,
  caption,
  scaleMax,
  empty = 'Nothing here yet.',
  className,
}: {
  segments: BarSegment[]
  /** The headline for a screen reader: "Receivables ₹4.2 L, of which ₹1.1 L is over 90 days old". */
  ariaLabel: string
  caption: string
  scaleMax?: number
  empty?: string
  className?: string
}) {
  const total = segments.reduce((n, s) => n + Math.max(s.value, 0), 0)
  const scale = Math.max(scaleMax ?? total, total, 1)
  const shares = percentages(segments.map((s) => s.value))
  return (
    <div className={cn('grid gap-2', className)}>
      <div role="img" aria-label={ariaLabel} className="flex h-7 w-full gap-0.5 overflow-hidden rounded-md bg-muted ring-1 ring-inset ring-[var(--faint)]">
        {total > 0 &&
          segments.map((s) =>
            s.value > 0 ? (
              <span
                key={s.key}
                title={`${s.label}: ${s.fullLabel ?? s.valueLabel}`}
                className="block h-full first:rounded-l-md last:rounded-r-md"
                style={{ ...segmentStyle(s.tone), width: `${Math.max((s.value / scale) * 100, 1.5)}%` }}
              />
            ) : null,
          )}
      </div>
      {total === 0 && <p className="text-sm text-muted-foreground">{empty}</p>}
      <ul className="grid grid-cols-2 gap-x-3 gap-y-0.5 sm:grid-cols-4">
        {segments.map((s, i) => {
          const body = (
            <>
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <span className="size-2.5 shrink-0 rounded-sm" style={segmentStyle(s.tone)} aria-hidden />
                <span className="truncate">{s.label}</span>
              </span>
              <span className={cn('num block text-sm font-semibold', s.value > 0 ? 'text-heading' : 'text-faint')} title={s.fullLabel}>
                {s.value > 0 ? s.valueLabel : '—'}
                {s.value > 0 && total > 0 && <span className="ml-1.5 text-xs font-normal text-muted-foreground">{shares[i]}%</span>}
              </span>
            </>
          )
          const box = 'grid min-h-11 content-center rounded-md px-1.5 -mx-1.5 sm:min-h-9'
          return (
            <li key={s.key}>
              {s.to && s.value > 0 ? (
                <Link to={s.to as never} params={s.params as never} search={s.search as never} className={cn(box, 'hover:bg-hover')}>
                  {body}
                </Link>
              ) : (
                <div className={box}>{body}</div>
              )}
            </li>
          )
        })}
      </ul>
      <ChartTable caption={caption} columns={['Part', 'Amount', 'Share']} rows={segments.map((s, i) => [s.label, s.fullLabel ?? s.valueLabel, total > 0 ? `${shares[i]}%` : '0%'])} />
    </div>
  )
}
