// Readings of GET /firm/metrics/: how its figures are worded, and which rows are listed.
//
// The server sends a ratio as null, never 0, when there is nothing to divide; the screens say so
// in words instead of showing 0% or NaN. People are listed alphabetically and clients by name,
// so no order ever reads as a ranking.

import type { FirmMetrics, MetricsClient, MetricsTurnaround } from '@/api/types'

export const NOT_ENOUGH_DATA = 'Not enough data yet'

/** 0.857 -> "86%". Null, undefined and anything that is not a number are null, never "0%" or "NaN%". */
export function percentText(ratio: number | null | undefined): string | null {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return null
  return `${Math.round(Math.min(1, Math.max(0, ratio)) * 100)}%`
}

/** 130 -> "2 h 10 min"; 45 -> "45 min". */
export function minutesText(minutes: number): string {
  const whole = Math.max(0, Math.round(minutes))
  const h = Math.trunc(whole / 60)
  const m = whole % 60
  if (h === 0) return `${m} min`
  return m === 0 ? `${h} h` : `${h} h ${m} min`
}

/** Median days: null is "Not enough data yet"; otherwise one decimal, "1 day" when it is exactly one. */
export function daysText(days: number | null | undefined): string {
  if (days === null || days === undefined || !Number.isFinite(days)) return NOT_ENOUGH_DATA
  const rounded = Math.round(days * 10) / 10
  if (rounded === 1) return '1 day'
  return `${Number.isInteger(rounded) ? rounded : rounded.toFixed(1)} days`
}

/** Clients with at least one reason, by name. The list is the server's; only the order is ours. */
export function attentionClients(metrics: Pick<FirmMetrics, 'clients'>): MetricsClient[] {
  return metrics.clients.filter((c) => c.needs_attention.length > 0).sort((a, b) => a.name.localeCompare(b.name))
}

/** People who had work in the period, alphabetical. */
export function turnaroundByName(metrics: Pick<FirmMetrics, 'turnaround'>): MetricsTurnaround[] {
  return [...metrics.turnaround].sort((a, b) => a.member.name.localeCompare(b.member.name))
}

/** The sentence under the time-saved figure. Always an estimate, never a measurement. */
export function estimateNote(minutesPerRow: number): string {
  return `Estimate: ${minutesPerRow} min per row assumed`
}
