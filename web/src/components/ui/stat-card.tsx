import { Link } from '@tanstack/react-router'
import type { ComponentProps, ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * One figure and what it means. The value is Inter, tabular, never the serif. When the card has a
 * destination the whole card is the link, so there is a single target and a single tab stop.
 */
export function StatCard({
  label,
  value,
  note,
  to,
  params,
  search,
  tone,
  className,
  valueTitle,
}: {
  label: string
  value: ReactNode
  note?: ReactNode
  to?: string
  params?: Record<string, string>
  search?: Record<string, unknown>
  tone?: 'plain' | 'attention'
  className?: string
  /** The full figure, when `value` is abbreviated. */
  valueTitle?: string
}) {
  const body = (
    <>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="num mt-1 text-[28px] font-semibold leading-8 text-heading" title={valueTitle} aria-label={valueTitle}>
        {value}
      </div>
      {note && <div className="mt-1 text-xs text-muted-foreground">{note}</div>}
    </>
  )
  const box = cn(
    'block rounded-lg border p-4 text-card-foreground',
    tone === 'attention' ? 'border-accent-edge bg-accent' : 'bg-card',
    to && 'hover:bg-hover',
    className,
  )
  if (to) {
    return (
      <Link to={to as never} params={params as never} search={search as never} className={box}>
        {body}
      </Link>
    )
  }
  return <div className={box}>{body}</div>
}

export function StatGrid({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('grid grid-cols-2 gap-3 lg:grid-cols-4', className)} {...props} />
}
