import { formatCompact, formatPaise } from '@/lib/format'
import { ChartTable } from './ChartTable'
import { segmentStyle } from './StackedBar'

export interface PairRow {
  key: string
  label: string
  current: number
  previous: number | null
}

/**
 * This year against last for each headline line: two bars per line on one scale, this year in the focus colour and last year
 * in the neutral. Bars start at zero; a negative figure is drawn at its size and written in brackets, as the statement prints it.
 */
export function PairedBars({ rows, current, previous, ariaLabel, caption }: { rows: PairRow[]; current: string; previous: string; ariaLabel: string; caption: string }) {
  const top = Math.max(1, ...rows.flatMap((r) => [Math.abs(r.current), Math.abs(r.previous ?? 0)]))
  const hasPrev = rows.some((r) => r.previous !== null)
  const money = (v: number) => (v < 0 ? `(${formatCompact(-v)})` : formatCompact(v))
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-hidden>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm" style={segmentStyle('focus')} /> {current}
        </span>
        {hasPrev && (
          <span className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-sm" style={segmentStyle('context')} /> {previous}
          </span>
        )}
      </div>
      <ul role="img" aria-label={ariaLabel} className="grid gap-3">
        {rows.map((r) => (
          <li key={r.key} className="grid min-w-0 gap-1">
            <span className="truncate text-sm text-heading" title={r.label}>
              {r.label}
            </span>
            {[{ v: r.current, tone: 'focus' as const }, ...(hasPrev && r.previous !== null ? [{ v: r.previous, tone: 'context' as const }] : [])].map((b, i) => (
              <span key={i} className="grid grid-cols-[minmax(0,1fr)_5.5rem] items-center gap-3">
                <span className="block h-2.5 rounded-sm bg-muted/60" aria-hidden>
                  <span className="block h-full rounded-sm" style={{ ...segmentStyle(b.tone), width: `${Math.max((Math.abs(b.v) / top) * 100, b.v === 0 ? 0 : 0.8)}%` }} />
                </span>
                <span className="num text-right text-sm text-heading" title={formatPaise(b.v)}>
                  {money(b.v)}
                </span>
              </span>
            ))}
          </li>
        ))}
      </ul>
      <ChartTable caption={caption} columns={['Line', current, previous]} rows={rows.map((r) => [r.label, formatPaise(r.current), r.previous === null ? '—' : formatPaise(r.previous)])} />
    </div>
  )
}
