import { useLayoutEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'

type Box = { x: number; y: number; w: number; h: number }

/**
 * A row of filter chips where exactly one is on. The filled shape glides to the chip you choose instead of each chip
 * switching its own fill. It moves one transform on one element, so it is cheap on an old machine; under reduced motion
 * the global rule makes it instant.
 */
export function GlideChips<T extends string>({
  options,
  value,
  onChange,
  label,
  className,
  variant = 'chips',
}: {
  /** `disabled` dims a chip that has nothing behind it; it cannot be chosen. */
  options: { value: T; label: string; disabled?: boolean }[]
  value: T
  onChange: (value: T) => void
  label: string
  className?: string
  /** 'segmented' is one framed switch with a light block on the choice, for a handful of ways to see the same thing. */
  variant?: 'chips' | 'segmented'
}) {
  const segmented = variant === 'segmented'
  const wrap = useRef<HTMLDivElement>(null)
  const chips = useRef<Record<string, HTMLButtonElement | null>>({})
  const [box, setBox] = useState<Box | null>(null)
  const measure = () => {
    const el = chips.current[value]
    if (!el || el.offsetWidth === 0) return
    const next = { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight }
    setBox((was) => (was && was.x === next.x && was.y === next.y && was.w === next.w && was.h === next.h ? was : next))
  }
  useLayoutEffect(measure)
  useLayoutEffect(() => {
    if (!wrap.current || typeof ResizeObserver === 'undefined') return
    const watcher = new ResizeObserver(measure)
    watcher.observe(wrap.current)
    return () => watcher.disconnect()
  })
  const glides = !!box

  return (
    <div ref={wrap} role="group" aria-label={label} className={cn('relative flex items-center', segmented ? 'gap-0.5 rounded-lg border border-border-strong bg-card p-1' : 'flex-wrap gap-1.5', className)}>
      {glides && (
        <span
          aria-hidden
          className={cn('absolute left-0 top-0 transition-[transform,width,height] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]', segmented ? 'rounded-md bg-foreground' : 'rounded-full bg-primary')}
          style={{ width: box.w, height: box.h, transform: `translate(${box.x}px, ${box.y}px)` }}
        />
      )}
      {options.map((o) => {
        const on = o.value === value
        return (
          <button
            key={o.value || 'any'}
            ref={(el) => {
              chips.current[o.value] = el
            }}
            type="button"
            aria-pressed={on}
            disabled={o.disabled && !on}
            onClick={() => onChange(o.value)}
            className={cn(
              'relative z-10 text-sm transition-colors duration-200',
              segmented ? 'rounded-md px-3 py-1 font-medium' : 'rounded-full border px-2.5 py-0.5',
              on
                ? segmented
                  ? glides
                    ? 'text-background'
                    : 'bg-foreground text-background'
                  : glides
                    ? 'border-transparent text-primary-foreground'
                    : 'border-primary bg-primary text-primary-foreground'
                : o.disabled
                  ? 'cursor-not-allowed text-faint opacity-60'
                  : 'hover:bg-hover',
            )}
          >
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
