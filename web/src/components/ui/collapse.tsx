import { useEffect, useRef, useState, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * Opens and closes its content with a smooth height and fade, using only CSS: the row of a grid grows from 0fr to 1fr.
 *
 * Its content must still be mounted while it closes, so a caller that unmounts on close uses `useClosing` to keep the
 * content for the length of the animation. Once fully open the clipping is lifted, so a menu or a focus ring inside is
 * never cut off. Under reduced motion the global rule makes the change instant.
 */
export const COLLAPSE_MS = 280

export function Collapse({ open, children, className }: { open: boolean; children: ReactNode; className?: string }) {
  // Starts closed and opens one frame after mounting, which is what lets the browser animate the first opening.
  const [shown, setShown] = useState(false)
  const [settled, setSettled] = useState(false)
  useEffect(() => {
    const frame = requestAnimationFrame(() => setShown(open))
    return () => cancelAnimationFrame(frame)
  }, [open])
  useEffect(() => {
    setSettled(false)
    if (!shown) return
    const timer = setTimeout(() => setSettled(true), COLLAPSE_MS + 40)
    return () => clearTimeout(timer)
  }, [shown])
  return (
    <div
      className={cn('grid transition-[grid-template-rows,opacity] ease-out', shown ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0', className)}
      style={{ transitionDuration: `${COLLAPSE_MS}ms` }}
      aria-hidden={shown ? undefined : true}
    >
      <div className={cn('min-h-0', settled && shown ? 'overflow-visible' : 'overflow-hidden')}>{children}</div>
    </div>
  )
}

/** The id that was open a moment ago, kept for the length of the closing animation, so its content can finish closing before it unmounts. */
export function useClosing(openId: string | null): string | null {
  const [closing, setClosing] = useState<string | null>(null)
  const last = useRef<string | null>(openId)
  useEffect(() => {
    const before = last.current
    last.current = openId
    if (before && before !== openId) {
      setClosing(before)
      const timer = setTimeout(() => setClosing((c) => (c === before ? null : c)), COLLAPSE_MS + 60)
      return () => clearTimeout(timer)
    }
  }, [openId])
  return closing
}
