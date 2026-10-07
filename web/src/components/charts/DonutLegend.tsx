import { Link } from '@tanstack/react-router'
import { lazy, Suspense, useMemo } from 'react'
import { percentages } from '@/lib/pct'
import { ChartTable } from './ChartTable'

const DonutPie = lazy(() => import('./DonutPie'))

export interface DonutRow {
  key: string
  label: string
  count: number
  /** A CSS colour, normally a `var(--chart-…)` token. */
  color: string
  to?: string
  params?: Record<string, string>
  search?: Record<string, unknown>
}

/**
 * A ring and, beside it, the rows that say the same thing in words: swatch, label, count and share.
 * The rows are the accessible data and the way in (each is a link when it has somewhere to go); the
 * ring only adds the shape. Shares come from one rounding rule so they always add up to 100.
 */
export function DonutLegend({
  rows,
  centerValue,
  centerLabel,
  summary,
  caption,
}: {
  rows: DonutRow[]
  centerValue: string | number
  centerLabel: string
  /** The conclusion, for a screen reader: "9 of 41 clients are signed off". */
  summary: string
  caption: string
}) {
  const total = rows.reduce((n, r) => n + r.count, 0)
  const shares = useMemo(() => percentages(rows.map((r) => r.count)), [rows])
  const slices = rows.map((r, i) => ({ key: r.key, label: r.label, count: r.count, percent: shares[i]!, color: r.color }))
  return (
    <div className="@container">
     <div className="grid items-center gap-4 @md:grid-cols-[10.5rem_minmax(0,1fr)] @md:gap-6">
      <div className="relative mx-auto size-40 @md:size-[10.5rem]">
        <div role="img" aria-label={summary} className="size-full">
          <Suspense fallback={<div className="skeleton size-full rounded-full" />}>
            <DonutPie slices={slices} total={total} />
          </Suspense>
        </div>
        <div className="pointer-events-none absolute inset-0 grid place-content-center text-center" aria-hidden>
          <div className="num text-2xl font-semibold leading-7 text-heading">{centerValue}</div>
          <div className="text-xs text-muted-foreground">{centerLabel}</div>
        </div>
        <ChartTable caption={caption} columns={['Group', 'Count', 'Share']} rows={slices.map((s) => [s.label, s.count, `${s.percent}%`])} />
      </div>
      <ul className="grid min-w-0 gap-0.5">
        {rows.map((r, i) => {
          const body = (
            <>
              <span className="size-3 shrink-0 rounded-sm" style={{ background: r.color }} aria-hidden />
              <span className="min-w-0 flex-1 truncate text-sm text-heading" title={r.label}>
                {r.label}
              </span>
              <span className="num w-8 text-right text-sm font-semibold text-heading">{r.count}</span>
              <span className="num w-10 text-right text-[13px] text-muted-foreground">{shares[i]}%</span>
            </>
          )
          const box = 'flex min-h-9 items-center gap-2.5 rounded-md px-2 -mx-2 max-sm:min-h-11'
          return (
            <li key={r.key}>
              {r.to ? (
                <Link to={r.to as never} params={r.params as never} search={r.search as never} className={`${box} hover:bg-hover`}>
                  {body}
                </Link>
              ) : (
                <div className={box}>{body}</div>
              )}
            </li>
          )
        })}
      </ul>
     </div>
    </div>
  )
}
