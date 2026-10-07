// What the dashboards read out of the firm portfolio. Pure, so the rules are tested and the three
// layouts agree: which layout a role gets, whether a client is on track, what a person should do next.
// Nothing here ranks or scores people; the figures are counts of clients and work.

import type { AttentionItem, Health, PortfolioClient } from '@/api/types'
import { formatCompact, formatDate, plural } from '@/lib/format'
import { nextTarget, type NextTarget } from '@/lib/overview'
import { isoOf } from '@/lib/period'

export type DashboardLayout = 'owner' | 'senior' | 'staff'

/** The layout for a signed-in role. Owners and read-only readers share one; anything unknown gets the least privileged. */
export function layoutFor(role: string | null | undefined): DashboardLayout {
  if (role === 'FIRM_ADMIN' || role === 'READ_ONLY') return 'owner'
  if (role === 'SENIOR_CA') return 'senior'
  return 'staff'
}

export type { Health } from '@/api/types'

export interface ClientHealth {
  health: Health
  /** Plain-words reasons, most serious first. Empty for a client on track. */
  reasons: string[]
}

/**
 * The server decides `health` (one definition for every screen); this only adds the reasons in words
 * from the figures the row carries, so a person can see why.
 */
export function clientHealth(c: PortfolioClient): ClientHealth {
  const reasons: string[] = []
  if (c.tds_overdue_paise) reasons.push(`TDS of ${formatCompact(c.tds_overdue_paise)} not deposited`)
  if (c.seal_due) reasons.push(`Seal date passed (${formatDate(c.seal_due)})`)
  if (c.months_missing.length) reasons.push(`${plural(c.months_missing.length, 'statement month')} missing`)
  if (c.failing_controls) reasons.push(`${plural(c.failing_controls, 'check')} failing`)
  if (c.blocking_unexplained) reasons.push(`${plural(c.blocking_unexplained, 'item')} blocking the seal`)
  return { health: c.health, reasons }
}

export interface HealthCounts {
  total: number
  onTrack: number
  atRisk: number
  overdue: number
  /** Clients with a passed sealing date, with TDS overdue, and with a missing month: the kinds of trouble. */
  sealLate: number
  tdsLate: number
  monthsLate: number
}

export function healthCounts(clients: PortfolioClient[]): HealthCounts {
  const out: HealthCounts = { total: clients.length, onTrack: 0, atRisk: 0, overdue: 0, sealLate: 0, tdsLate: 0, monthsLate: 0 }
  for (const c of clients) {
    const { health } = clientHealth(c)
    if (health === 'on_track') out.onTrack += 1
    else if (health === 'at_risk') out.atRisk += 1
    else out.overdue += 1
    if (c.seal_due) out.sealLate += 1
    if (c.tds_overdue_paise) out.tdsLate += 1
    if (c.months_missing.length) out.monthsLate += 1
  }
  return out
}

/** Counts the dashboards read from the portfolio's new fields; absent fields count as nothing. */
export function sealingFigures(clients: PortfolioClient[]) {
  const waiting = clients.filter((c) => c.oldest_pending_approval_days !== undefined && c.oldest_pending_approval_days !== null)
  return {
    readyToSeal: clients.filter((c) => c.ready_to_seal).length,
    waitingForApproval: waiting.length,
    oldestDays: waiting.reduce((n, c) => Math.max(n, c.oldest_pending_approval_days ?? 0), 0),
  }
}

/** A thing for a person to do: one line, one button to exactly where it is done. */
export interface Action {
  key: string
  client: string
  clientId: string
  title: string
  detail?: string
  target: NextTarget
  cta: string
  /** Lower comes first. */
  rank: number
}

const WORDS: Record<string, { cta: string; rank: number }> = {
  sign_off: { cta: 'Review', rank: 0 },
  send_for_review: { cta: 'Send', rank: 3 },
  place: { cta: 'Open', rank: 2 },
  post: { cta: 'Open', rank: 2 },
  upload: { cta: 'Upload', rank: 1 },
}

function titleFor(c: PortfolioClient): string {
  const n = c.next_step.count
  switch (c.next_step.code) {
    case 'upload':
      return 'Upload the bank statement'
    case 'place':
      return `Sort ${plural(n, 'entry', 'entries')} into accounts`
    case 'post':
      return `Record ${plural(n, 'entry', 'entries')} in the books`
    case 'send_for_review':
      return 'Send the books for review'
    case 'sign_off':
      return 'Review and sign off the books'
    default:
      return c.next_step.label
  }
}

/** Every client with something to do, as actions. Late things come first, then the order the work flows; ties by name. */
export function actionsFor(clients: PortfolioClient[]): Action[] {
  return clients
    .filter((c) => c.next_step.code !== 'none')
    .map((c): Action => {
      const word = WORDS[c.next_step.code] ?? { cta: 'Open', rank: 4 }
      const health = clientHealth(c)
      const late = health.health === 'overdue'
      return {
        key: c.id,
        client: c.name,
        clientId: c.id,
        title: titleFor(c),
        detail: late ? health.reasons[0] : undefined,
        target: nextTarget(c.next_step.code),
        cta: word.cta,
        rank: word.rank + (late ? -10 : 0),
      }
    })
    .sort((a, b) => a.rank - b.rank || a.client.localeCompare(b.client))
}

/** What falls due within `days` of `today` (inclusive), from a list the server sends for a longer window. */
export function dueWithin<T extends { date: string }>(deadlines: T[], days: number, today: Date): T[] {
  const end = isoOf(new Date(today.getFullYear(), today.getMonth(), today.getDate() + days))
  return deadlines.filter((d) => d.date <= end)
}

export interface AttentionGroup {
  clientId: string
  client: string
  items: number
  /** Items the server calls critical: something is overdue or failed. */
  critical: number
  /** Where the most serious item is fixed (an app path and its query). */
  to: string
  search: Record<string, string>
  /** The most serious item in words, and how many others there are. */
  text: string
  others: number
}

/** The server's attention items, one row per client: most critical first, then most items, then name. */
export function groupAttention(items: AttentionItem[], limit = 8): AttentionGroup[] {
  const order = { critical: 0, high: 1, medium: 2 } as const
  const by = new Map<string, AttentionItem[]>()
  for (const item of items) by.set(item.client, [...(by.get(item.client) ?? []), item])
  return [...by.values()]
    .map((list): AttentionGroup => {
      const sorted = [...list].sort((a, b) => order[a.severity] - order[b.severity])
      const top = sorted[0]!
      return {
        clientId: top.client,
        client: top.client_name,
        items: list.length,
        critical: list.filter((i) => i.severity === 'critical').length,
        to: top.to,
        search: top.search,
        text: top.text,
        others: list.length - 1,
      }
    })
    .sort((a, b) => b.critical - a.critical || b.items - a.items || a.client.localeCompare(b.client))
    .slice(0, limit)
}
