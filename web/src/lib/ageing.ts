// Ageing buckets, in one order with one set of words, wherever money is aged: the Payables and Receivables
// reports, the firm dashboard and the client page. Money is whole paise; nothing here does arithmetic on strings.

import type { BarSegment, SegmentTone } from '@/components/charts/StackedBar'
import { formatCompact, formatPaise } from '@/lib/format'

/** Oldest last, so the bar reads from fresh to stale. */
export const AGE_BUCKETS = ['0-30', '31-60', '61-90', 'Over 90'] as const
export type AgeBucket = (typeof AGE_BUCKETS)[number]

export const AGE_LABEL: Record<AgeBucket, string> = {
  '0-30': '0-30 days',
  '31-60': '31-60 days',
  '61-90': '61-90 days',
  'Over 90': 'Over 90 days',
}

const TONE: Record<AgeBucket, SegmentTone> = { '0-30': 'age1', '31-60': 'age2', '61-90': 'age3', 'Over 90': 'bad' }

type Link = Pick<BarSegment, 'to' | 'params' | 'search'>

/** The four segments for any set of bucket amounts, always all four and always in order; unknown buckets are ignored. */
export function ageSegments(amounts: Partial<Record<string, number>>, link?: Link): BarSegment[] {
  return AGE_BUCKETS.map((b) => {
    const paise = Math.max(amounts[b] ?? 0, 0)
    return { key: b, label: AGE_LABEL[b], value: paise, valueLabel: formatCompact(paise), fullLabel: formatPaise(paise), tone: TONE[b], ...link }
  })
}

/** Segments from the portfolio's list shape `[{bucket, amount_paise}]`. */
export function ageSegmentsFromList(list: { bucket: string; amount_paise: number }[], link?: Link): BarSegment[] {
  return ageSegments(Object.fromEntries(list.map((b) => [b.bucket, b.amount_paise])), link)
}

/** What the client snapshot gives: only the total and how much of it is over 90 days. Two parts, same meaning and tones. */
export function overNinetySegments(totalPaise: number, over90Paise: number): BarSegment[] {
  const over = Math.min(Math.max(over90Paise, 0), Math.max(totalPaise, 0))
  const rest = Math.max(totalPaise, 0) - over
  return [
    { key: 'recent', label: 'Up to 90 days', value: rest, valueLabel: formatCompact(rest), fullLabel: formatPaise(rest), tone: 'age2' },
    { key: 'Over 90', label: AGE_LABEL['Over 90'], value: over, valueLabel: formatCompact(over), fullLabel: formatPaise(over), tone: 'bad' },
  ]
}

export const sumSegments = (segments: BarSegment[]) => segments.reduce((n, s) => n + s.value, 0)
