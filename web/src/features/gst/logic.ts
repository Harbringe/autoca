// The rules of the GST reconciliation screens that are not drawing: which months may be asked for,
// which decisions the server will accept on which kind of row, who may sign a run off, what step a
// run is at, and how a difference is worded. Pure, so each is tested without a screen.
//
// Every amount is an integer in paise; sums stay integers and nothing here uses a float.

import type { GstDecisionKind, GstGroup, GstGroupKind, GstInvoice, GstReport, GstRow, GstRun, GstItcStatus } from '@/api/types'
import { formatPaise } from '@/lib/format'

// --- months -----------------------------------------------------------------

const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

/** GST began on 1 July 2017; no return exists for an earlier month. */
export const FIRST_PERIOD = '2017-07'

const PERIOD = /^(\d{4})-(0[1-9]|1[0-2])$/

export const periodOf = (year: number, month: number): string => `${year}-${String(month).padStart(2, '0')}`

/** "2026-08" or "2026-08-01" -> "August 2026". */
export function periodName(value: string): string {
  const match = /^(\d{4})-(\d{2})/.exec(value)
  return match ? `${MONTH_NAMES[Number(match[2]) - 1] ?? match[2]} ${match[1]}` : value
}

/** The month a return is asked for, checked before the request: the server's pattern, then the calendar. */
export function periodProblem(period: string, today: Date): string | null {
  const match = PERIOD.exec(period)
  if (!match) return 'Choose the return month.'
  if (period < FIRST_PERIOD) return 'GST began in July 2017, so there is no earlier return.'
  if (period > periodOf(today.getFullYear(), today.getMonth() + 1)) return 'That month has not started yet, so there is nothing to reconcile.'
  return null
}

/** Months to choose from, newest first, from the current month back `count` months (never before GST began). */
export function monthChoices(today: Date, count = 36): { value: string; label: string }[] {
  const out: { value: string; label: string }[] = []
  for (let i = 0; i < count; i++) {
    const d = new Date(today.getFullYear(), today.getMonth() - i, 1)
    const value = periodOf(d.getFullYear(), d.getMonth() + 1)
    if (value < FIRST_PERIOD) break
    out.push({ value, label: periodName(value) })
  }
  return out
}

/** The month a return is usually being prepared for: the one that just ended. */
export function defaultPeriod(today: Date): string {
  const d = new Date(today.getFullYear(), today.getMonth() - 1, 1)
  const value = periodOf(d.getFullYear(), d.getMonth() + 1)
  return value < FIRST_PERIOD ? FIRST_PERIOD : value
}

// --- files ------------------------------------------------------------------

export const REGISTER_FORMATS = ['.xlsx', '.xlsm', '.csv'] as const
export const PORTAL_FORMATS = ['.json', '.xlsx'] as const

export const extensionOf = (name: string): string => {
  const dot = name.lastIndexOf('.')
  return dot < 0 ? '' : name.slice(dot).toLowerCase()
}

/** A file the server would refuse by its name alone, caught before the upload. */
export function fileProblem(file: { name: string; size: number } | undefined, accepted: readonly string[]): string | null {
  if (!file) return 'Choose a file first.'
  if (file.size === 0) return 'The file is empty.'
  if (!accepted.includes(extensionOf(file.name))) return `Upload a file ending in ${listFormats(accepted)}.`
  return null
}

export function listFormats(accepted: readonly string[]): string {
  if (accepted.length === 1) return accepted[0]!
  return `${accepted.slice(0, -1).join(', ')} or ${accepted[accepted.length - 1]}`
}

// --- decisions --------------------------------------------------------------

/** The kinds of row a person has to look at; the server refuses sign-off while any has no decision. */
export const NEEDS_DECISION: readonly GstGroupKind[] = ['amount_mismatch', 'tax_head_mismatch', 'possible_match']

const ACCEPT_OR_CLAIM: readonly GstGroupKind[] = ['possible_match', 'amount_mismatch', 'tax_head_mismatch']
const DISALLOW: readonly GstGroupKind[] = ['matched', 'possible_match', 'amount_mismatch', 'tax_head_mismatch', 'import', 'isd_credit']

export const DECISION_ORDER: readonly GstDecisionKind[] = ['accept_match', 'claim_itc', 'disallow_itc', 'defer', 'note']

export const DECISION_LABEL: Record<GstDecisionKind, string> = {
  accept_match: 'Accept as a match',
  claim_itc: 'Claim the credit',
  disallow_itc: 'Do not claim the credit',
  defer: 'Decide later',
  note: 'Add a note only',
}

export const DECISION_HINT: Record<GstDecisionKind, string> = {
  accept_match: 'The books and GSTR-2B are the same invoice; the credit follows GSTR-2B.',
  claim_itc: 'Claim the credit even though the figures differ.',
  disallow_itc: 'Keep the credit out of Table 4, with the reason in the note.',
  defer: 'Leave it for a later month. It no longer blocks sign-off.',
  note: 'Saved with the row. It is not a decision and does not change any figure.',
}

/**
 * What the server will accept on a row of this kind (gst/services.py `_ALLOWED`). Offering anything
 * else would only come back as a 409. `defer` and `note` apply to every row.
 */
export function allowedDecisions(kind: GstGroupKind): GstDecisionKind[] {
  return DECISION_ORDER.filter((d) => {
    if (d === 'accept_match' || d === 'claim_itc') return ACCEPT_OR_CLAIM.includes(kind)
    if (d === 'disallow_itc') return DISALLOW.includes(kind)
    return true
  })
}

/** The word on a row that has a decision. A note is not a decision and never shows here. */
export const DECISION_BADGE: Record<GstDecisionKind, string> = {
  accept_match: 'Accepted',
  claim_itc: 'Claimed',
  disallow_itc: 'Not claimed',
  defer: 'Decide later',
  note: 'Note',
}

export const ITC_LABEL: Record<GstItcStatus, string> = {
  eligible: 'Eligible',
  blocked: 'Blocked, section 17(5)',
  not_eligible: 'Not claimable yet',
  rcm_on_payment: 'Reverse charge, claimable after payment',
}

// --- sign-off ---------------------------------------------------------------

export interface SignOffInput {
  /** `gst.sign_off` from /me/. */
  permitted: boolean
  role: string | null | undefined
  membershipId: string | null | undefined
  /** The client's Senior CA, if it has one. */
  leadId: string | null | undefined
}

/** The server's rule beyond the permission: a firm administrator, the client's lead, or any approver while it has no lead. */
export function mayFinalise({ permitted, role, membershipId, leadId }: SignOffInput): boolean {
  if (!permitted) return false
  if (role === 'FIRM_ADMIN') return true
  return !leadId || leadId === membershipId
}

export type SignOffGate = { ok: true } | { ok: false; reason: string }

/** Whether this run can be signed off by this person now, and if not, why, in a sentence. */
export function signOffGate(report: GstReport, who: SignOffInput): SignOffGate {
  if (report.status === 'signed_off') return { ok: false, reason: 'This run is already signed off.' }
  if (!who.permitted) return { ok: false, reason: 'Your role cannot sign off a reconciliation.' }
  if (!mayFinalise(who)) return { ok: false, reason: 'Only the client’s Senior CA or a firm administrator can sign this off.' }
  if (!report.has_register || !report.has_portal) return { ok: false, reason: 'Upload the purchase register and GSTR-2B, then run the match.' }
  if (report.groups.length === 0) return { ok: false, reason: 'Run the match before signing off.' }
  const open = report.summary.unresolved
  if (open > 0) return { ok: false, reason: `${open === 1 ? '1 difference has' : `${open} differences have`} no decision yet.` }
  return { ok: true }
}

// --- where a run stands -----------------------------------------------------

export type StepKey = 'register' | 'portal' | 'match' | 'decide' | 'sign_off'

export interface Step {
  key: StepKey
  label: string
  done: boolean
}

export const matched = (report: GstReport): boolean => report.groups.length > 0

/** The five steps and which are done, from the report alone. */
export function stepsOf(report: GstReport): Step[] {
  const hasMatches = matched(report)
  return [
    { key: 'register', label: 'Purchase register', done: report.has_register },
    { key: 'portal', label: 'GSTR-2B', done: report.has_portal },
    { key: 'match', label: 'Match', done: hasMatches },
    { key: 'decide', label: 'Decide', done: hasMatches && report.summary.unresolved === 0 },
    { key: 'sign_off', label: 'Sign off', done: report.status === 'signed_off' },
  ]
}

/** The first step not done, or null when the run is signed off. */
export function currentStep(report: GstReport): StepKey | null {
  return stepsOf(report).find((s) => !s.done)?.key ?? null
}

// --- reading a row ----------------------------------------------------------

/** All four tax heads of one invoice in paise. */
export const taxOf = (inv: Pick<GstInvoice, 'igst_paise' | 'cgst_paise' | 'sgst_paise' | 'cess_paise'> | null): number | null =>
  inv ? inv.igst_paise + inv.cgst_paise + inv.sgst_paise + inv.cess_paise : null

/** The row's reference invoice: the books' where there is one, otherwise GSTR-2B's. */
export const invoiceOf = (row: GstRow): GstInvoice => (row.book ?? row.portal) as GstInvoice

/** Books minus GSTR-2B, in paise: the taxable value and the four tax heads together. */
export function differenceOf(row: GstRow): { taxable: number; tax: number } {
  const d = row.differences ?? {}
  return {
    taxable: d.taxable_paise ?? 0,
    tax: (d.igst_paise ?? 0) + (d.cgst_paise ?? 0) + (d.sgst_paise ?? 0) + (d.cess_paise ?? 0),
  }
}

/** "Books higher by 900.00", "Books lower by 900.00", or null when the figures agree. The sign is words, not a minus. */
export function differenceWords(paise: number): string | null {
  if (paise === 0) return null
  return `Books ${paise > 0 ? 'higher' : 'lower'} by ${formatPaise(Math.abs(paise), { symbol: false })}`
}

/** A credit note reduces credit; it is marked in words so the sign is never the only signal. */
export const isCreditNote = (row: GstRow): boolean => invoiceOf(row).section === 'CDN'

/** Whether a row still needs a person: a kind the server counts as unresolved, with no decision. */
export const needsDecision = (kind: GstGroupKind, row: GstRow): boolean => NEEDS_DECISION.includes(kind) && row.decision === null

/** Groups a person must act on start open; matched and the rest start closed. */
export const startsOpen = (group: GstGroup): boolean => group.rows.some((r) => needsDecision(group.kind, r)) || group.kind === 'missing_in_2b' || group.kind === 'missing_in_books'

/** The row with this id, and the group it is in. */
export function findRow(report: GstReport, id: string): { group: GstGroup; row: GstRow } | undefined {
  for (const group of report.groups) {
    const row = group.rows.find((r) => r.id === id)
    if (row) return { group, row }
  }
  return undefined
}

// --- the firm landing -------------------------------------------------------

/** Latest first: by month, then the signed-off status last so a draft of the same month is shown. */
export function latestRun(runs: GstRun[]): GstRun | undefined {
  return [...runs].sort((a, b) => b.period_start.localeCompare(a.period_start) || (a.status === 'draft' ? -1 : 1))[0]
}

/** The distinct GSTINs that have a run, in the order they first appear. */
export function gstinsOf(runs: GstRun[]): string[] {
  return [...new Set(runs.map((r) => r.gstin))]
}
