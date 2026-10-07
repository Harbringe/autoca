// A big figure and what it means: the StatCard, plus the two things a dashboard adds. A comparison line
// only where a real comparison exists (never invented, never for a live stock figure), written as an arrow
// and words so colour is not the message, and an optional progress bar for "this much of that".

import { ArrowDown, ArrowRight, ArrowUp } from 'lucide-react'
import type { ReactNode } from 'react'
import { ProgressBar } from '@/components/charts/ProgressBar'
import { StatCard } from '@/components/ui/stat-card'
import { cn } from '@/lib/utils'

export interface Delta {
  /** In words: "2 more than last month". */
  text: string
  direction: 'up' | 'down' | 'flat'
  /** true: the direction is good news, false: bad news, null/undefined: just a change, no colour. */
  good?: boolean | null
}

const ICON = { up: ArrowUp, down: ArrowDown, flat: ArrowRight } as const

export function KpiCard({
  label,
  value,
  valueTitle,
  note,
  delta,
  progress,
  to,
  params,
  search,
  tone,
  loading,
}: {
  label: string
  value: ReactNode
  valueTitle?: string
  note?: ReactNode
  delta?: Delta
  progress?: { value: number; max: number; label: string }
  to?: string
  params?: Record<string, string>
  search?: Record<string, unknown>
  tone?: 'plain' | 'attention'
  loading?: boolean
}) {
  if (loading) {
    return (
      <div className="skeleton h-[7.25rem] rounded-lg" aria-busy="true">
        <span className="sr-only">Loading: {label}</span>
      </div>
    )
  }
  const Arrow = delta ? ICON[delta.direction] : null
  return (
    <StatCard
      label={label}
      value={value}
      valueTitle={valueTitle}
      to={to}
      params={params}
      search={search}
      tone={tone}
      className="h-full"
      note={
        <>
          {note && <span className="block">{note}</span>}
          {progress && <ProgressBar value={progress.value} max={progress.max} label={progress.label} className="mt-2" />}
          {delta && Arrow && (
            <span className={cn('mt-1 flex items-center gap-1', delta.good === true && 'text-success', delta.good === false && 'text-destructive')}>
              <Arrow className="size-3" aria-hidden /> {delta.text}
            </span>
          )}
        </>
      }
    />
  )
}
