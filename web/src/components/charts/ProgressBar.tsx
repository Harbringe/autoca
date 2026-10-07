import { pct } from '@/lib/pct'
import { cn } from '@/lib/utils'

/**
 * A bar for "this much of that". The words beside it say the same thing; the bar adds the shape.
 * `label` names it for a screen reader ("7 of 12 months done").
 */
export function ProgressBar({
  value,
  max,
  label,
  className,
  tone = 'primary',
}: {
  value: number
  max: number
  label: string
  className?: string
  tone?: 'primary' | 'accent'
}) {
  const width = pct(value, max)
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={Math.min(value, max)}
      aria-valuetext={label}
      className={cn('h-2 w-full overflow-hidden rounded-full bg-muted', className)}
    >
      <div className={cn('h-full rounded-full', tone === 'primary' ? 'bg-primary' : 'bg-accent-foreground')} style={{ width: `${width}%` }} />
    </div>
  )
}
