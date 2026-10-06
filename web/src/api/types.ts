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
export type Client = Omit<Schemas['Client'], 'lead'> & { lead: Person | null }
export type Job = Schemas['Job']
export type Statement = Schemas['Statement']
export type StatementTransaction = Schemas['StatementTransaction']
export type BankAccount = Schemas['BankAccount']
export type LedgerAccount = Schemas['LedgerAccount']
export type Party = Schemas['Party']
export type Bill = Schemas['Bill']
export type BillDetail = Schemas['BillDetail']
export type BillCreateRequest = Schemas['BillCreateRequest']
export type SettlementContext = Schemas['SettlementContext']
export type Outstanding = Schemas['Outstanding']
export type OutstandingParty = Schemas['OutstandingParty']
export type OutstandingBill = Schemas['OutstandingBill']
export type PartyStatement = Schemas['PartyStatement']
export type OpenItems = Schemas['OpenItems']
export type OpenItem = Schemas['OpenItem']
export type OpeningStanding = Schemas['OpeningStanding']
export type InvoiceReading = Schemas['InvoiceReading']
export type CloseReport = Schemas['CloseReport']
export type FoundParties = Schemas['FoundParties']
export type FoundParty = Schemas['FoundParty']
export type CloseItem = Schemas['CloseItem']
export type Rule = Schemas['ClassificationRule']
export type JournalEntry = Schemas['JournalEntry']
export type JournalLine = Schemas['JournalLine']
export type LedgerRow = Schemas['LedgerRow']
export type EntryChange = Schemas['EntryChange']
export type NextBatch = Schemas['NextBatch']
export type ReviewSummary = Schemas['ReviewSummary']
export type BooksStatus = Schemas['BooksStatus']
export type TrialBalance = Schemas['TrialBalance']
export type ProfitAndLoss = Schemas['ProfitAndLoss']
export type BalanceSheet = Schemas['BalanceSheet']
export type LedgerBalance = Schemas['LedgerBalance']
export type ReportFooter = Schemas['ReportFooter']
export type BalanceCheck = Schemas['BalanceCheck']

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
  /** Rows left for the assistant, which reads them a few at a time after the upload. */
  waiting_for_assistant: number
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

// --- team (generated) -------------------------------------------------------

export type Person = Schemas['Person']
export type MetricKey = keyof Schemas['WorkTotals']
/** The schema types `key` as a string; the server only ever sends the keys of `WorkTotals`. */
export type Metric = Omit<Schemas['Metric'], 'key'> & { key: MetricKey }
export type WorkTotals = Schemas['WorkTotals']
export type Member = Schemas['Member']
export type MemberWithWork = Schemas['MemberWithWork']
export type MembersResponse = Omit<Schemas['MembersResponse'], 'metrics' | 'can'> & {
  metrics: Metric[]
  can: Omit<Schemas['MembersCan'], 'invite_roles' | 'role_options'> & { invite_roles: Role[]; role_options: Role[] }
}
export type MemberWork = Omit<Schemas['MemberWorkResponse'], 'metrics'> & { metrics: Metric[] }
export type Invite = Schemas['InviteRecord']
export type TeamClients = Schemas['TeamClientsResponse']
export type TeamClient = Schemas['TeamClient']
export type TeamEvent = Schemas['TeamEvent']

// --- firm overview (generated) ----------------------------------------------

export type FirmOverview = Schemas['FirmOverview']
export type OverviewClient = Schemas['OverviewClient']
export type OverviewTotals = Schemas['OverviewTotals']
export type Stage = Schemas['StageEnum']

// --- firm and audit ---------------------------------------------------------

export type FirmSettings = Schemas['FirmResponse']

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

// --- GST reconciliation (generated) -----------------------------------------

export type GstRegistration = Schemas['Registration']
export type GstRun = Schemas['RunListItem']
export type GstReport = Schemas['RunReport']
export type GstGroup = Schemas['ReportGroup']
export type GstRow = Schemas['ReportRow']
export type GstInvoice = Schemas['ReportInvoice']
export type GstGstr3bLine = Schemas['ReportGstr3bLine']
export type GstGroupKind = Schemas['ReportGroupKindEnum']
export type GstDecisionKind = Schemas['ReportDecisionKindEnum']
export type GstItcStatus = Schemas['ItcStatusEnum']

// --- firm metrics (generated) -----------------------------------------------

export type FirmMetrics = Schemas['FirmMetrics']
export type MetricsClient = Schemas['MetricsClient']
export type MetricsTurnaround = Schemas['MetricsTurnaround']
export type AttentionReason = Schemas['AttentionReason']
