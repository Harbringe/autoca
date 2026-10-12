import { useEffect, useState, type CSSProperties } from 'react'
import { pct } from '@/lib/pct'
import { cn } from '@/lib/utils'

// Bars that grow instead of jumping. The first time a bar is shown in a session it fills from empty, so the page settles in;
// after that it starts at its real value (coming back to a screen does not replay it), and whenever the value changes later
// it moves smoothly to the new one, so finishing a task is seen as the bar advancing. Only width and colour change, so it is
// cheap on an old machine; under reduced motion the global rule makes every change instant.

const seen = new Set<string>()

/** The value to draw: it starts at 0 the first time `id` is shown, at `target` after that, and follows `target` from then on. */
export function useGrown(target: number, id: string): { value: number; first: boolean } {
  const [first] = useState(() => !seen.has(id))
  const [value, setValue] = useState(first ? 0 : target)
  useEffect(() => {
    seen.add(id)
    const frame = requestAnimationFrame(() => setValue(target))
    return () => cancelAnimationFrame(frame)
  }, [target, id])
  return { value, first }
}

/** Bars with no `id` of their own are known by their label with the numbers taken out, so "7 of 12" and "8 of 12" are one bar. */
const keyOf = (label: string) => label.replace(/[\d.,%₹]+/g, '#')

/** The filled part of a bar: a block whose width follows `percent`, growing the first time it is shown. */
export function GrowFill({ percent, id, className, style }: { percent: number; id: string; className?: string; style?: CSSProperties }) {
  const { value } = useGrown(percent, id)
  return <span className={cn('block h-full transition-[width] duration-700 ease-out', className)} style={{ ...style, width: `${value}%` }} />
}

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
  id,
}: {
  value: number
  max: number
  label: string
  className?: string
  tone?: 'primary' | 'accent'
  /** What makes two bars "the same bar" for the first-time animation. Defaults to the label without its numbers. */
  id?: string
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
      <GrowFill percent={width} id={id ?? keyOf(label)} className={cn('rounded-full', tone === 'primary' ? 'bg-primary' : 'bg-accent-foreground')} />
    </div>
  )
}

/**
 * One segment per item, the finished ones first. Each segment fills when its item is done: one after another the first time
 * the meter is shown, and as each task is completed afterwards.
 */
export function SegmentedMeter({ total, done, label, id, className }: { total: number; done: number; label: string; id: string; className?: string }) {
  const { value, first } = useGrown(done, id)
  return (
    <div role="img" aria-label={label} className={cn('flex gap-1.5', className)}>
      {Array.from({ length: total }, (_, i) => (
        <span key={i} className="h-2 flex-1 overflow-hidden rounded-full bg-border">
          <span
            className={cn('block h-full origin-left rounded-full bg-success transition-transform duration-500 ease-out', i < value ? 'scale-x-100' : 'scale-x-0')}
            style={first ? { transitionDelay: `${i * 140}ms` } : undefined}
          />
        </span>
      ))}
    </div>
  )
}
