import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { formatCompact, formatPaise } from '@/lib/format'
import type { BridgeStep } from '@/lib/reportSeries'
import { cn } from '@/lib/utils'
import { ChartTable } from './ChartTable'
import { segmentStyle } from './StackedBar'

/** What a step is worth: a cost is what it took off; income and the result are where they end. */
const shownOf = (s: BridgeStep) => (s.tone === 'out' ? s.from - s.to : s.to)

/**
 * From what came in to what was kept: income, then each big cost taken off in turn, then the result. Each bar floats from where
 * the last one ended on one shared scale with a zero line, so a loss visibly hangs to the left of zero. Plain HTML: the labels wrap,
 * the figure sits on its bar, and nothing is truncated on an axis. The same steps are in a hidden table.
 */
export function Bridge({ steps, ariaLabel, caption }: { steps: BridgeStep[]; ariaLabel: string; caption: string }) {
  const values = steps.flatMap((s) => [s.from, s.to, 0])
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = Math.max(max - min, 1)
  const at = (v: number) => ((v - min) / span) * 100
  return (
    <div>
      <ul role="img" aria-label={ariaLabel} className="grid gap-1.5">
        {steps.map((s) => {
          const left = at(Math.min(s.from, s.to))
          const width = Math.max((Math.abs(s.to - s.from) / span) * 100, s.to === s.from ? 0 : 0.8)
          const shown = shownOf(s)
          return (
            <li key={s.key} className="grid items-center gap-x-3 gap-y-0.5 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)_6.5rem]">
              <span className={cn('flex min-w-0 items-center gap-1.5 text-sm', s.result ? 'font-semibold text-heading' : 'text-muted-foreground')} title={s.label}>
                {s.result && (s.tone === 'bad' ? <AlertTriangle className="size-4 shrink-0 text-destructive" aria-hidden /> : <CheckCircle2 className="size-4 shrink-0 text-success" aria-hidden />)}
                <span className="truncate">{s.label}</span>
              </span>
              <span className="relative block h-6 rounded-sm bg-muted/60" aria-hidden>
                <span className="absolute inset-y-0 w-px bg-[var(--faint)]" style={{ left: `${at(0)}%` }} />
                <span className="absolute inset-y-1 rounded-sm" style={{ ...segmentStyle(s.tone), left: `${left}%`, width: `${width}%` }} />
              </span>
              <span className={cn('num text-right text-sm', s.result ? 'font-semibold text-heading' : 'text-heading')} title={formatPaise(shown)}>
                {s.tone === 'out' ? (shown > 0 ? '−' : '+') : shown < 0 ? '−' : ''}
                {formatCompact(Math.abs(shown))}
              </span>
            </li>
          )
        })}
      </ul>
      <ChartTable caption={caption} columns={['Step', 'Amount']} rows={steps.map((s) => [s.label, formatPaise(shownOf(s))])} />
    </div>
  )
}
