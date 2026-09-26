import { formatDrCr, formatPaise } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * An amount, the way a ledger sets it: right-aligned, tabular, two decimals,
 * lakh grouping. Prefer the server's own `display` string when the API sent one
 * -- it is formatted where the figure was computed. Bare `paise` (GST) is
 * formatted here.
 */
export function Money({
  display,
  paise,
  className,
  symbol = true,
  muted,
}: {
  display?: string | null
  paise?: number | null
  className?: string
  symbol?: boolean
  /** Dim a zero, so a column of figures shows where the money actually is. */
  muted?: boolean
}) {
  const text = display ?? (paise === null || paise === undefined ? '—' : formatPaise(paise, { symbol }))
  const zero = paise === 0 || /^\D*0\.00$/.test(text)
  return <span className={cn('num whitespace-nowrap text-right', muted && zero && 'text-muted-foreground/60', className)}>{text}</span>
}

/** A balance with its side: "₹6,03,490.57 Dr". Never a signed number. */
export function Balance({ net, className }: { net: number; className?: string }) {
  return <span className={cn('num whitespace-nowrap text-right', className)}>{formatDrCr(net)}</span>
}
