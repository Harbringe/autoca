import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { formatCompact, formatPaise } from '@/lib/format'
import type { Pair, PairSide } from '@/lib/reportSeries'
import { cn } from '@/lib/utils'
import { StackedBar } from './StackedBar'

function Side({ side, scaleMax, emptyLine }: { side: PairSide; scaleMax: number; emptyLine: string }) {
  return (
    <div className="grid gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-medium text-heading">{side.title}</h3>
        <span className="num text-lg font-semibold text-heading" title={formatPaise(side.total)}>
          {formatCompact(side.total)}
        </span>
      </div>
      <StackedBar
        segments={side.segments}
        scaleMax={scaleMax}
        empty={emptyLine}
        ariaLabel={`${side.title}: ${formatCompact(side.total)}`}
        caption={`${side.title}, by line`}
        className="[&_ul]:sm:grid-cols-2 [&_ul]:lg:grid-cols-4"
      />
    </div>
  )
}

/**
 * Two totals that must agree, drawn as two bars on one scale: debits against credits, or liabilities and profit against assets.
 * Each bar is split into its biggest lines, labelled directly. Below, the gap is said with an icon, never by colour alone;
 * the bars themselves show it as two lengths.
 */
export function BalancePair({ pair, agree, gapWords }: { pair: Pair; agree: string; gapWords: (gap: number) => string }) {
  const sum = (s: PairSide) => s.segments.reduce((n, x) => n + x.value, 0)
  const scaleMax = Math.max(sum(pair.left), sum(pair.right), 1)
  const ok = pair.balanced && pair.gap === 0
  return (
    <div className="grid gap-4">
      <Side side={pair.left} scaleMax={scaleMax} emptyLine="Nothing on this side." />
      <Side side={pair.right} scaleMax={scaleMax} emptyLine="Nothing on this side." />
      <p className={cn('flex items-center gap-2 text-sm font-medium', ok ? 'text-success' : 'text-destructive')} role="status">
        {ok ? <CheckCircle2 className="size-4 shrink-0" aria-hidden /> : <AlertTriangle className="size-4 shrink-0" aria-hidden />}
        {ok ? agree : gapWords(pair.gap)}
      </p>
    </div>
  )
}
