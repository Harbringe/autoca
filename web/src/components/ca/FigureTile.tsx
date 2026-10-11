// One headline figure for a command strip: a small icon and label, ONE big number, an optional unit or change, and a one-line
// caption. No paragraphs. The whole tile is the link when the figure counts something that has its own screen.

import { Link } from '@tanstack/react-router'
import type { LucideIcon } from 'lucide-react'
import { ArrowDown, ArrowRight, ArrowUp } from 'lucide-react'
import type { ReactNode } from 'react'
import { Sparkline } from '@/components/charts/Sparkline'
import { cn } from '@/lib/utils'

export interface TileDelta {
  /** In words and figures: "4 more than before". */
  text: string
  direction: 'up' | 'down' | 'flat'
  good?: boolean | null
}

const ARROW = { up: ArrowUp, down: ArrowDown, flat: ArrowRight } as const

export function FigureTile({
  icon: Icon,
  label,
  value,
  unit,
  delta,
  caption,
  spark,
  tone = 'plain',
  to,
  params,
  search,
  loading,
}: {
  icon: LucideIcon
  label: string
  value: ReactNode
  /** A small word or unit after the number ("of 12"). */
  unit?: string
  delta?: TileDelta
  caption?: ReactNode
  spark?: { values: number[]; label: string }
  tone?: 'plain' | 'good' | 'watch' | 'bad'
  to?: string
  params?: Record<string, string>
  search?: Record<string, unknown>
  loading?: boolean
}) {
  if (loading) {
    return (
      <div className="skeleton h-[7.5rem] rounded-xl" aria-busy="true">
        <span className="sr-only">Loading: {label}</span>
      </div>
    )
  }
  const Arrow = delta ? ARROW[delta.direction] : null
  const body = (
    <>
      <div className="flex items-center justify-between gap-2 text-[13px] text-muted-foreground">
        <span className="truncate">{label}</span>
        <Icon
          className={cn('size-4 shrink-0', tone === 'bad' && 'text-destructive', tone === 'watch' && 'text-accent-foreground', tone === 'good' && 'text-success')}
          aria-hidden
        />
      </div>
      <div className="mt-1.5 flex items-baseline gap-2">
        <span className="num text-[32px] font-semibold leading-9 text-heading">{value}</span>
        {unit && <span className="text-sm text-muted-foreground">{unit}</span>}
        {delta && Arrow && (
          <span className={cn('flex items-center gap-0.5 text-xs', delta.good === true && 'text-success', delta.good === false && 'text-destructive', delta.good == null && 'text-muted-foreground')}>
            <Arrow className="size-3" aria-hidden /> {delta.text}
          </span>
        )}
      </div>
      {caption && <div className="mt-1 text-[13px] leading-snug text-muted-foreground">{caption}</div>}
      {spark && spark.values.length >= 2 && (
        <div className="mt-2">
          <Sparkline values={spark.values} ariaLabel={spark.label} width={120} height={24} />
        </div>
      )}
    </>
  )
  const box = cn(
    'block h-full rounded-xl border bg-card p-4 text-card-foreground',
    tone === 'bad' && 'border-destructive/40',
    tone === 'watch' && 'border-accent-edge',
    to && 'hover:bg-hover',
  )
  return to ? (
    <Link to={to as never} params={params as never} search={search as never} className={box}>
      {body}
    </Link>
  ) : (
    <div className={box}>{body}</div>
  )
}
