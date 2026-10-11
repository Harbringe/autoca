// What the dashboards read out of the firm portfolio. Pure, so the rules are tested and the three
// layouts agree: which layout a role gets, whether a client is on track, what a person should do next.
// Nothing here ranks or scores people; the figures are counts of clients and work.

import type { AttentionItem, Health, Portfolio, PortfolioClient } from '@/api/types'
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

// ---------------------------------------------------------------------------------------------------------------
// The words, once. These are the owner's definitions and every screen reads them from here:
//   Late         a statutory or seal date has passed and the work is not done.
//   At risk      a date falls within 7 days, or a statement month is missing.
//   Work waiting entries still to be decided: unresolved + pending approval + assistant-posted not yet checked.
//                Books sent for review are a different unit (a book, not an entry) and are counted apart, never added in.
//
// Until the server's own `health` agrees with these, standing is derived here from fields the API already sends.
// The server fields that should take over are listed in `STANDING_SERVER_FIELDS`.
// ---------------------------------------------------------------------------------------------------------------

/** How many days ahead a date makes a client "at risk". */
export const AT_RISK_DAYS = 7

/** What the browser derives today and the server should send instead (so this file can shrink). */
export const STANDING_SERVER_FIELDS = [
  'PortfolioClient.health computed with the three definitions above (today it treats a passed seal date as at risk, ignores dates within 7 days, and counts failing checks)',
  'PortfolioClient.next_tds_due (date of the earliest unpaid TDS deposit, per client id; today only names under `deadlines`)',
  'PortfolioClient.health_reasons (the causes, in order)',
] as const

export interface ClientHealth {
  health: Health
  /** Plain-words causes of Late or At risk, most serious first. Empty for a client on track. */
  reasons: string[]
  /** Failing checks and items blocking the seal: shown beside the standing, never part of it. */
  watch: string[]
}

export interface StandingContext {
  today?: Date
  /** ISO dates of unpaid TDS deposits falling due, by client id. Built by `standingContext`. */
  tdsDue?: Map<string, string[]>
}

const addDays = (d: Date, days: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + days)

/** TDS deposits falling due, matched to a client by name only when that name is unique in the portfolio. */
export function standingContext(data: Pick<Portfolio, 'clients' | 'deadlines'> | undefined, today: Date = new Date()): StandingContext {
  const tdsDue = new Map<string, string[]>()
  if (data) {
    const byName = new Map<string, string[]>()
    for (const c of data.clients) byName.set(c.name, [...(byName.get(c.name) ?? []), c.id])
    for (const d of data.deadlines) {
      if (d.label !== 'TDS deposit') continue
      for (const name of d.clients) {
        const ids = byName.get(name)
        if (ids?.length === 1) tdsDue.set(ids[0]!, [...(tdsDue.get(ids[0]!) ?? []), d.date])
      }
    }
  }
  return { today, tdsDue }
}

/**
 * Where a client stands. Late when a seal date has passed unsealed or TDS is past its deposit date; at risk when a
 * seal or TDS date is within 7 days or a statement month is missing; otherwise on track.
 */
export function clientHealth(c: PortfolioClient, ctx: StandingContext = {}): ClientHealth {
  const today = ctx.today ?? new Date()
  const todayIso = isoOf(today)
  const soon = isoOf(addDays(today, AT_RISK_DAYS))
  const within = (iso: string | null | undefined) => !!iso && iso >= todayIso && iso <= soon
  const late: string[] = []
  const risk: string[] = []
  if (c.tds_overdue_paise) late.push(`TDS of ${formatCompact(c.tds_overdue_paise)} not deposited`)
  if (c.seal_due) late.push(`Seal date passed (${formatDate(c.seal_due)})`)
  if (c.months_missing.length) risk.push(`${plural(c.months_missing.length, 'statement month')} missing`)
  if (within(c.next_seal_date)) risk.push(`Seal date ${formatDate(c.next_seal_date!)}`)
  const tds = (ctx.tdsDue?.get(c.id) ?? []).filter(within).sort()[0]
  if (tds) risk.push(`TDS deposit due ${formatDate(tds)}`)
  const watch: string[] = []
  if (c.failing_controls) watch.push(`${plural(c.failing_controls, 'check')} failing`)
  if (c.blocking_unexplained) watch.push(`${plural(c.blocking_unexplained, 'item')} blocking the seal`)
  const health: Health = late.length ? 'overdue' : risk.length ? 'at_risk' : 'on_track'
  return { health, reasons: [...late, ...risk], watch }
}

export interface HealthCounts {
  total: number
  onTrack: number
  atRisk: number
  overdue: number
  /** Clients with a passed sealing date, with TDS overdue, with a missing month, and with a date inside 7 days: the kinds of trouble. */
  sealLate: number
  tdsLate: number
  monthsLate: number
  dueSoon: number
}

export function healthCounts(clients: PortfolioClient[], ctx: StandingContext = {}): HealthCounts {
  const out: HealthCounts = { total: clients.length, onTrack: 0, atRisk: 0, overdue: 0, sealLate: 0, tdsLate: 0, monthsLate: 0, dueSoon: 0 }
  for (const c of clients) {
    const h = clientHealth(c, ctx)
    if (h.health === 'on_track') out.onTrack += 1
    else if (h.health === 'at_risk') out.atRisk += 1
    else out.overdue += 1
    if (c.seal_due) out.sealLate += 1
    if (c.tds_overdue_paise) out.tdsLate += 1
    if (c.months_missing.length) out.monthsLate += 1
    if (h.reasons.some((r) => /^(Seal date \d|TDS deposit due)/.test(r))) out.dueSoon += 1
  }
  return out
}

/** The reason a client is at risk or late, as one line for a KPI note: "2 past a seal date · 1 with TDS overdue". */
export function lateNote(h: HealthCounts): string {
  const parts = [h.sealLate && `${h.sealLate} past a seal date`, h.tdsLate && `${h.tdsLate} with TDS overdue`].filter(Boolean)
  return parts.length ? parts.join(' · ') : 'No seal or TDS date has passed'
}

export function riskNote(h: HealthCounts): string {
  const parts = [h.dueSoon && `${h.dueSoon} with a date in ${AT_RISK_DAYS} days`, h.monthsLate && `${h.monthsLate} with a month missing`].filter(Boolean)
  return parts.length ? parts.join(' · ') : `No date within ${AT_RISK_DAYS} days, no month missing`
}

/**
 * Work waiting: entries still to be decided, the same on every screen (and the same as the server's per-person
 * "open"). Books awaiting a senior's review are a count of books, so they are never added in.
 */
export function workWaiting(t: { unresolved: number; pending_approval: number; ai_unchecked: number }): number {
  return t.unresolved + t.pending_approval + t.ai_unchecked
}

/** Books (clients) with a review request open: reported beside work waiting, never inside it. */
export function booksInReview(t: { review_pending: number }): number {
  return t.review_pending
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
export function actionsFor(clients: PortfolioClient[], ctx: StandingContext = {}): Action[] {
  return clients
    .filter((c) => c.next_step.code !== 'none')
    .map((c): Action => {
      const word = WORDS[c.next_step.code] ?? { cta: 'Open', rank: 4 }
      const health = clientHealth(c, ctx)
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
