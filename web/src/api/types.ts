// Shapes the OpenAPI schema does not describe.
//
// Most of the API's types are generated (src/api/schema.d.ts, from
// web/openapi.yaml). The endpoints below are plain Django views, which the
// schema generator cannot see into, so their shapes are written down here from
// the views that produce them. If one of those views changes, this is the file
// to change with it -- and `npm run gen:api` is the check that the rest still
// agree.

import type { components } from './schema'

type Schemas = components['schemas']

export type Me = Schemas['Me']
export type Client = Schemas['Client'] & { lead: Person | null }
export type Job = Schemas['Job']
export type Statement = Schemas['Statement']
export type StatementTransaction = Schemas['StatementTransaction']
export type BankAccount = Schemas['BankAccount']
export type LedgerAccount = Schemas['LedgerAccount']
export type Party = Schemas['Party']
export type Rule = Schemas['ClassificationRule']
export type JournalEntry = Schemas['JournalEntry']
export type JournalLine = Schemas['JournalLine']
export type EntryChange = Schemas['EntryChange']
export type ReviewSummary = Schemas['ReviewSummary']
export type BooksStatus = Schemas['BooksStatus']
export type TrialBalance = Schemas['TrialBalance']
export type ProfitAndLoss = Schemas['ProfitAndLoss']
export type BalanceSheet = Schemas['BalanceSheet']
export type LedgerBalance = Schemas['LedgerBalance']
export type ReportFooter = Schemas['ReportFooter']
export type BalanceCheck = Schemas['BalanceCheck']
export type TallyExport = Schemas['TallyExport']

/** One side of the entry a row makes, as the server describes it for display. */
export interface EntryLeg {
  side: 'Dr' | 'Cr'
  ledger: string | null
  group?: string | null
  is_bank: boolean
  amount_display: string
}

export interface PartyCandidate {
  party: string
  name: string
  score: number
  why: string
  source: string
}

/** A row waiting for a decision. The schema leaves these two lists untyped. */
export type Classification = Omit<Schemas['Classification'], 'entry_legs' | 'party_candidates'> & {
  entry_legs: EntryLeg[]
  party_candidates: PartyCandidate[]
}

export type PlacementResult = Omit<Schemas['PlacementResult'], 'classification'> & { classification: Classification }

/** What a statement upload's job reports when it finishes. */
export interface IngestResult {
  statement: string
  bank_account: string
  is_new: boolean
  rows_created: number
  rows_already_present: number
  needs_opening_confirmation: boolean
  suggested: number
  queued_for_review: number
  model_suggested: number
  model_declined: number
  model_proposed: number
  model_error: string
  auto_posted: number
  /** Where this statement's rows stand now. The three add up to the rows in the statement. */
  rows_posted?: number
  rows_ready_to_post?: number
  rows_need_ledger?: number
}

/** Tally's primary groups, in the order a chart of accounts is read. */
export const LEDGER_GROUPS = [
  ['CAPITAL', 'Capital Account'],
  ['LOAN', 'Loans (Liability)'],
  ['CREDITOR', 'Sundry Creditors'],
  ['DUTIES_AND_TAXES', 'Duties & Taxes'],
  ['BANK', 'Bank Accounts'],
  ['CASH', 'Cash-in-Hand'],
  ['DEBTOR', 'Sundry Debtors'],
  ['INVESTMENT', 'Investments'],
  ['DIRECT_INCOME', 'Direct Incomes'],
  ['INDIRECT_INCOME', 'Indirect Incomes'],
  ['DIRECT_EXPENSE', 'Direct Expenses'],
  ['INDIRECT_EXPENSE', 'Indirect Expenses'],
  ['SUSPENSE', 'Suspense A/c'],
] as const

export type LedgerGroup = (typeof LEDGER_GROUPS)[number][0]
export const GROUP_LABEL: Record<string, string> = Object.fromEntries(LEDGER_GROUPS)

export const TDS_SECTIONS = [
  ['', 'No TDS'],
  ['192', '192 Salary'],
  ['194A', '194A Interest'],
  ['194C', '194C Contractors'],
  ['194H', '194H Commission'],
  ['194I', '194I Rent'],
  ['194J', '194J Professional fees'],
  ['194Q', '194Q Purchase of goods'],
] as const

export type Role = 'FIRM_ADMIN' | 'SENIOR_CA' | 'STAFF' | 'READ_ONLY'

export const ROLE_LABEL: Record<Role, string> = {
  FIRM_ADMIN: 'Firm administrator',
  SENIOR_CA: 'Senior CA',
  STAFF: 'Staff',
  READ_ONLY: 'Read only',
}

// --- /auth/* ----------------------------------------------------------------

export type MfaStep = 'setup' | 'verify'

export interface LoginResponse {
  detail: string
  /** null only when the second factor is switched off for local development. */
  mfa: MfaStep | null
}

export interface MfaSetupResponse {
  provisioningUri: string
}

export interface InviteDescription {
  email: string
  full_name: string
  firm: string
  role_display: string
  team: string
  has_account: boolean
}

// --- team -------------------------------------------------------------------

export interface Person {
  id: string
  name: string
  role: Role
  role_display: string
  is_owner: boolean
  is_active: boolean
}

export type MetricKey =
  | 'statements_uploaded'
  | 'rows_placed'
  | 'entries_approved'
  | 'entries_corrected'
  | 'ledgers_created'
  | 'rules_written'
  | 'proposals_decided'
  | 'model_runs'

export interface Metric {
  key: MetricKey
  label: string
}

export interface Member extends Person {
  user_id: string
  email: string
  full_name: string
  scope_all_clients: boolean
  manager: Person | null
  last_login: string | null
  created_at: string
  is_me: boolean
  clients: { id: string; name: string; how: 'assigned' | 'leads' }[]
  can: { manage: boolean; set_active: boolean }
}

export interface MembersResponse {
  period: { from: string; to: string }
  metrics: Metric[]
  can: { invite: boolean; invite_roles: Role[]; manage: boolean; manage_admins: boolean }
  leads: Person[]
  results: (Member & { work: Record<MetricKey, number> })[]
}

export interface MemberWork {
  member: Person
  period: { from: string; to: string }
  metrics: Metric[]
  totals: Record<MetricKey, number>
  by_client: ({ id: string | null; name: string } & Record<MetricKey, number>)[]
  by_day: { date: string; count: number }[]
  open_work: { id: string; name: string; unresolved: number; pending_approval: number }[]
}

export interface Invite {
  id: string
  email: string
  full_name: string
  role: Role
  role_display: string
  manager: Person | null
  expires_at: string
  created_at: string
  created_by: string | null
}

export interface TeamClients {
  can: { set_lead: boolean }
  assignable: Person[]
  results: {
    id: string
    name: string
    lead: Person | null
    team: (Person & { assigned_at: string; on_my_team: boolean })[]
    unresolved: number
    pending_approval: number
  }[]
}

export interface TeamEvent {
  id: string
  kind: string
  kind_display: string
  /** A snapshot of the names at the time: actor, member, client, from, to, email, role ... */
  detail: Record<string, unknown>
  member_id: string | null
  client_id: string | null
  at: string
}

// --- firm and audit ---------------------------------------------------------

export interface FirmSettings {
  id: string
  name: string
  created_at: string
  owner: Person | null
  admins: Person[]
  counts: { active_members: number; senior_cas: number; staff: number; clients: number }
  can: { rename: boolean; transfer: boolean }
}

export interface AuditRow {
  id: string
  at: string
  who: string
  email: string | null
  action: string
  client_id: string | null
  succeeded: boolean
  status_code: number
  ip_address: string | null
}

export interface Page<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}
