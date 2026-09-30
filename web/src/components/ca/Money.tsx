import { formatCompact, formatDrCr, formatPaise } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * An amount, the way a ledger sets it: right-aligned, tabular, two decimals,
 * lakh grouping. Prefer the server's own `display` string when the API sent one
 * -- it is formatted where the figure was computed. Bare `paise` (GST) is
 * formatted here.
 *
 * Dense tables put the rupee sign in the column header and pass `symbol={false}` for figures
 * formatted here; strings from the server are shown as sent. In a Debit/Credit pair, `dash`
 * writes a zero as a dash; `muted` only dims it (a nil balance in a trial balance stays 0.00).
 * `compact` (Cr / L) is for dashboard cards only and always carries the full figure in its title.
 */
export function Money({
  display,
  paise,
  className,
  symbol = true,
  muted,
  dash,
  compact,
}: {
  display?: string | null
  paise?: number | null
  className?: string
  symbol?: boolean
  /** Dim a zero (kept as 0.00, as auditors expect in a trial balance). */
  muted?: boolean
  /** Write a zero as a dash in a Debit/Credit column, so it shows where the money actually is. */
  dash?: boolean
  compact?: boolean
}) {
  const full = display ?? (paise === null || paise === undefined ? '—' : formatPaise(paise, { symbol }))
  const zero = paise === 0 || /^\D*0\.00$/.test(full)
  if (dash && zero) {
    return (
      <span className={cn('num whitespace-nowrap text-right text-faint', className)}>
        <span className="sr-only">{full}</span>
        <span aria-hidden>–</span>
      </span>
    )
  }
  if (compact && display == null && paise != null) {
    return (
      <span className={cn('num whitespace-nowrap text-right', className)} title={full} aria-label={full}>
        {formatCompact(paise)}
      </span>
    )
  }
  return <span className={cn('num whitespace-nowrap text-right', muted && zero && 'text-faint', className)}>{full}</span>
}

/** A balance with its side: "₹6,03,490.57 Dr". Never a signed number. */
export function Balance({ net, className }: { net: number; className?: string }) {
  return <span className={cn('num whitespace-nowrap text-right', className)}>{formatDrCr(net)}</span>
}
