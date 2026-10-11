// The series the report pictures are drawn from. Pure and tested: every figure comes from the whole-paise fields the report
// APIs already send, never from a display string, and every picture's total is the server's total, not a re-sum that could drift.

import type { BarSegment, SegmentTone } from '@/components/charts/StackedBar'
import type { BalanceSheet, InventoryItem, LedgerBalance, ProfitAndLoss, Statements, TdsMonth, TrialBalance } from '@/api/types'
import { GROUP_LABEL } from '@/api/types'
import { formatCompact, formatPaise } from '@/lib/format'

export type LineKind = 'asset' | 'expense' | 'liability' | 'income'

/** A line's balance on its natural side: positive when it sits where it normally does, negative when it is the other way round. */
export function naturalPaise(r: Pick<LedgerBalance, 'closing_debit_paise' | 'closing_credit_paise'>, kind: LineKind): number {
  const debitNatural = kind === 'asset' || kind === 'expense'
  return debitNatural ? r.closing_debit_paise - r.closing_credit_paise : r.closing_credit_paise - r.closing_debit_paise
}

export interface Part {
  label: string
  value: number
}

/** The biggest `n` positive parts, then everything else as one "Other" part. Order: largest first, Other last. */
export function topWithOther(parts: Part[], n: number, otherLabel = 'Other'): Part[] {
  const positive = parts.filter((p) => p.value > 0).sort((a, b) => b.value - a.value || a.label.localeCompare(b.label))
  if (positive.length <= n) return positive
  const rest = positive.slice(n)
  return [...positive.slice(0, n), { label: `${otherLabel} (${rest.length})`, value: rest.reduce((t, p) => t + p.value, 0) }]
}

const RAMP: SegmentTone[] = ['part1', 'part2', 'part3', 'part4']

/** Parts as bar segments: the ramp from darkest, the last "Other" in the neutral tone. */
export function partSegments(parts: Part[], otherLast = true): BarSegment[] {
  return parts.map((p, i) => {
    const isOther = otherLast && i === parts.length - 1 && /\(\d+\)$/.test(p.label)
    return {
      key: `${i}-${p.label}`,
      label: p.label,
      value: p.value,
      valueLabel: formatCompact(p.value),
      fullLabel: formatPaise(p.value),
      tone: isOther ? 'context' : (RAMP[Math.min(i, RAMP.length - 1)] as SegmentTone),
    }
  })
}

// --- Profit and loss -------------------------------------------------------------------------------------------------

export interface BridgeStep {
  key: string
  label: string
  from: number
  to: number
  tone: SegmentTone
  /** The step is the result row: it gets a good/bad icon and bold label. */
  result?: boolean
}

/**
 * Income, then each of the biggest expense heads taken off in turn, then the result. Bars float from where the last one
 * ended, so the eye follows the money from what came in to what was kept (or lost). `other` is the remainder to the server's
 * own expense total, so the walk always ends where the report says it ends.
 */
export function plBridge(pl: Pick<ProfitAndLoss, 'expenses' | 'total_income_paise' | 'total_expenses_paise' | 'net_profit_paise'>, heads = 5): BridgeStep[] {
  const top = topWithOther(
    pl.expenses.map((e) => ({ label: e.name, value: naturalPaise(e, 'expense') })),
    heads,
    'Other heads',
  )
  const shown = top.reduce((t, p) => t + p.value, 0)
  const parts = [...top]
  const remainder = pl.total_expenses_paise - shown
  if (remainder !== 0) {
    const i = parts.findIndex((p) => p.label.startsWith('Other heads'))
    if (i >= 0) parts[i] = { ...parts[i]!, value: parts[i]!.value + remainder }
    else parts.push({ label: 'Other', value: remainder })
  }
  const steps: BridgeStep[] = [{ key: 'income', label: 'Income', from: 0, to: pl.total_income_paise, tone: 'focus' }]
  let cursor = pl.total_income_paise
  parts.forEach((p, i) => {
    steps.push({ key: `e${i}`, label: p.label, from: cursor, to: cursor - p.value, tone: 'out' })
    cursor -= p.value
  })
  const profit = pl.net_profit_paise >= 0
  steps.push({ key: 'net', label: profit ? 'Net profit' : 'Net loss', from: 0, to: pl.net_profit_paise, tone: profit ? 'good' : 'bad', result: true })
  return steps
}

// --- Balance sheet and trial balance --------------------------------------------------------------------------------

export interface PairSide {
  title: string
  /** The server's total for this side, signed as the report prints it. */
  total: number
  segments: BarSegment[]
  /** Lines sitting on the other side of their natural balance; they cannot be drawn in a bar and are said in words. */
  oppositePaise: number
}

export interface Pair {
  left: PairSide
  right: PairSide
  /** left total minus right total, in paise. */
  gap: number
  balanced: boolean
}

/**
 * A side's segments: its biggest lines, then (when any line sits the wrong way round, an overdrawn bank, say) one "opposite
 * balances" part sized by what those lines come to, so the irregularity is in the picture and in the scale, not in a footnote.
 */
function side(title: string, total: number, parts: Part[], opposite: number, n: number): PairSide {
  const segments = partSegments(topWithOther(parts, n))
  if (opposite > 0) {
    segments.push({ key: 'opposite', label: 'Balances the other way', value: opposite, valueLabel: formatCompact(opposite), fullLabel: formatPaise(opposite), tone: 'watch' })
  }
  return { title, total, segments, oppositePaise: opposite }
}

const negatives = (parts: Part[]) => parts.filter((p) => p.value < 0).reduce((t, p) => t + -p.value, 0)

/** Liabilities and profit against assets, each side split into its biggest lines. */
export function bsPair(bs: Pick<BalanceSheet, 'assets' | 'liabilities' | 'total_assets_paise' | 'total_liabilities_and_profit_paise' | 'net_profit_paise' | 'balances'>, lines = 4): Pair {
  const liabilities: Part[] = bs.liabilities.map((l) => ({ label: l.name, value: naturalPaise(l, 'liability') }))
  liabilities.push({ label: bs.net_profit_paise >= 0 ? 'Net profit for the year' : 'Net loss for the year', value: bs.net_profit_paise })
  const assets: Part[] = bs.assets.map((a) => ({ label: a.name, value: naturalPaise(a, 'asset') }))
  return {
    left: side('Liabilities and profit', bs.total_liabilities_and_profit_paise, liabilities, negatives(liabilities), lines),
    right: side('Assets', bs.total_assets_paise, assets, negatives(assets), lines),
    gap: bs.total_liabilities_and_profit_paise - bs.total_assets_paise,
    balanced: bs.balances,
  }
}

/** Debit balances against credit balances, each split by ledger group. */
export function tbPair(tb: Pick<TrialBalance, 'rows' | 'total_debit_paise' | 'total_credit_paise' | 'balances'>, groups = 4): Pair {
  const debit = new Map<string, number>()
  const credit = new Map<string, number>()
  for (const r of tb.rows) {
    const g = GROUP_LABEL[r.group ?? ''] ?? (r.group || 'Other')
    debit.set(g, (debit.get(g) ?? 0) + r.closing_debit_paise)
    credit.set(g, (credit.get(g) ?? 0) + r.closing_credit_paise)
  }
  const toParts = (m: Map<string, number>): Part[] => [...m.entries()].map(([label, value]) => ({ label, value }))
  return {
    left: side('Debit balances', tb.total_debit_paise, toParts(debit), 0, groups),
    right: side('Credit balances', tb.total_credit_paise, toParts(credit), 0, groups),
    gap: tb.total_debit_paise - tb.total_credit_paise,
    balanced: tb.balances,
  }
}

// --- TDS ------------------------------------------------------------------------------------------------------------

export interface MonthTotal {
  key: string
  year: number
  month: number
  deducted: number
  deposited: number
  late: boolean
}

/** Deducted and deposited per calendar month across sections, in time order. */
export function tdsByMonth(months: Pick<TdsMonth, 'year' | 'month' | 'deducted_paise' | 'deposited_paise' | 'overdue'>[]): MonthTotal[] {
  const by = new Map<string, MonthTotal>()
  for (const m of months) {
    const key = `${m.year}-${String(m.month).padStart(2, '0')}`
    const cur = by.get(key) ?? { key, year: m.year, month: m.month, deducted: 0, deposited: 0, late: false }
    cur.deducted += m.deducted_paise
    cur.deposited += m.deposited_paise
    cur.late = cur.late || m.overdue
    by.set(key, cur)
  }
  return [...by.values()].sort((a, b) => a.key.localeCompare(b.key))
}

// --- Inventory ------------------------------------------------------------------------------------------------------

/** The biggest items by closing value (positive values only); the rest as one part. */
export function topStockItems(items: Pick<InventoryItem, 'name' | 'closing_value_paise'>[], n = 6): Part[] {
  return topWithOther(items.map((i) => ({ label: i.name, value: i.closing_value_paise })), n, 'Other items')
}

// --- ICAI statements -----------------------------------------------------------------------------------------------

export interface HeadlinePair {
  key: string
  label: string
  current: number
  previous: number | null
}

/** The total lines of a statement (the ones the report itself bolds), as this year against last; lines that are nil in both years are left out. */
export function statementHeadlines(rows: Statements['balance_sheet'], max = 5): HeadlinePair[] {
  return rows
    .filter((r) => r.kind === 'total' && r.current_paise !== null && (r.current_paise !== 0 || (r.previous_paise ?? 0) !== 0))
    .slice(0, max)
    .map((r) => ({ key: r.key, label: r.label, current: r.current_paise ?? 0, previous: r.previous_paise }))
}
