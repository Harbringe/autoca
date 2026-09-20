// Shapes as the API sends them. Money always arrives twice: `*_paise` is the
// integer to compute with, `*_display` is the string to show. Never format the
// integer here -- see api/fields.py for why.

export interface Firm {
  id: string
  name: string
  is_active: boolean
  created_at: string
}

export interface Me {
  id: string
  email: string
  full_name: string
  firm: Firm | null
  membership_id: string | null
  role: string | null
  role_display: string | null
  is_owner: boolean
  permissions: string[]
}

export interface Client {
  id: string
  name: string
  fy_start: string
  /** What the business does, in the CA's words; read by the ledger-suggesting model. */
  business_profile: string
  created_at: string
  lead: { id: string; name: string } | null
  /** May approve and correct this client's entries: its lead, or a firm admin. */
  can_sign_off: boolean
  can_post: boolean
}

export type JobStatus = 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'

export interface Job {
  id: string
  kind: string
  status: JobStatus
  progress: number
  message: string
  result: Record<string, unknown>
  error: string
  error_code: string
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface BankAccount {
  id: string
  label: string
  client: string
  bank_code: string
  account_last4: string
  ifsc: string
  ledger_name: string
  opening_balance_paise: number | null
  opening_balance_display: string | null
  opening_as_of: string | null
  has_opening_balance: boolean
  is_active: boolean
  created_at: string
  account_number?: string
  account_holder?: string
}

export interface Document {
  id: string
  kind: string
  original_filename: string
  sha256: string
  byte_size: number
  page_count: number
  pipeline_tier: string
  status: string
  failure_reason: string
  created_at: string
}

export interface Statement {
  id: string
  bank_account: string
  bank_account_label: string
  document: Document
  period_start: string
  period_end: string
  opening_balance_paise: number
  opening_balance_display: string
  closing_balance_paise: number
  closing_balance_display: string
  total_debit_paise: number
  total_debit_display: string
  total_credit_paise: number
  total_credit_display: string
  transaction_count: number
  parser: string
  parser_version: number
  created_at: string
}

export interface Transaction {
  id: string
  statement: string
  bank_account: string
  row_number: number
  value_date: string
  narration: string
  cheque_number: string
  branch_code: string
  debit_paise: number
  debit_display: string
  credit_paise: number
  credit_display: string
  balance_paise: number
  balance_display: string
  amount_paise: number
  amount_display: string
  is_debit: boolean
}

export type ReviewBand = 'HIGH' | 'ADVISED' | 'JUDGEMENT'
export type Method = 'RULE' | 'UNRESOLVED' | 'REVIEWED' | 'LLM'

// A suggestion for who a payee is. Never applied on its own -- a person
// confirms it, and only then is the spelling remembered.
export interface PartyCandidate {
  party: string
  name: string
  score: number
  why: string
  source: string
}

// One side of the entry a transaction makes. Every transaction touches two
// accounts -- the bank and whatever the money was for -- so a row always has
// exactly two legs, and an unplaced row shows the missing one as null.
export interface EntryLeg {
  side: 'Dr' | 'Cr'
  ledger: string | null
  group?: string | null
  is_bank: boolean
  amount_display: string
}

export interface Classification {
  id: string
  transaction: Transaction
  ledger: string | null
  ledger_name: string | null
  ledger_status: LedgerStatus | null
  ledger_group: string | null
  ledger_group_display: string | null
  ledger_opened_by_model: boolean
  voucher_type: 'Payment' | 'Receipt' | 'Contra' | 'Journal' | null
  entry_legs: EntryLeg[]
  book_narration: string
  open_question: string
  party: string | null
  party_name: string | null
  party_resolution: '' | 'AUTO' | 'CANDIDATE' | 'NEW' | 'CONFIRMED'
  party_candidates: PartyCandidate[]
  rcm: boolean
  tds_section: string
  method: Method
  method_display: string
  rationale: string
  confidence: number
  review_band: ReviewBand
  needs_review: boolean
  channel: string
  counterparty: string
  is_self_transfer: boolean
  is_posted: boolean
  reviewed_at: string | null
}

export interface ReviewSummary {
  high: number
  advised: number
  judgement: number
  total: number
  bulk_approvable: number
  unresolved: number
  pending_approval: number
}

export interface PlacementResult {
  classification: Classification
  rule_learned: string | null
  also_placed: number
}

export type LedgerGroup =
  | 'BANK'
  | 'CASH'
  | 'DEBTOR'
  | 'CREDITOR'
  | 'INDIRECT_EXPENSE'
  | 'DIRECT_EXPENSE'
  | 'INDIRECT_INCOME'
  | 'DIRECT_INCOME'
  | 'DUTIES_AND_TAXES'
  | 'LOAN'
  | 'INVESTMENT'
  | 'CAPITAL'
  | 'SUSPENSE'

export const LEDGER_GROUPS: { value: LedgerGroup; label: string }[] = [
  { value: 'INDIRECT_EXPENSE', label: 'Indirect Expenses' },
  { value: 'DIRECT_EXPENSE', label: 'Direct Expenses' },
  { value: 'INDIRECT_INCOME', label: 'Indirect Incomes' },
  { value: 'DIRECT_INCOME', label: 'Direct Incomes' },
  { value: 'BANK', label: 'Bank Accounts' },
  { value: 'CASH', label: 'Cash-in-Hand' },
  { value: 'DEBTOR', label: 'Sundry Debtors' },
  { value: 'CREDITOR', label: 'Sundry Creditors' },
  { value: 'DUTIES_AND_TAXES', label: 'Duties & Taxes' },
  { value: 'LOAN', label: 'Loans (Liability)' },
  { value: 'INVESTMENT', label: 'Investments' },
  { value: 'CAPITAL', label: 'Capital Account' },
  { value: 'SUSPENSE', label: 'Suspense A/c' },
]

export const TDS_SECTIONS: { value: string; label: string }[] = [
  { value: '', label: 'None' },
  { value: '192', label: '192 — Salary' },
  { value: '194A', label: '194A — Interest' },
  { value: '194C', label: '194C — Contractors' },
  { value: '194H', label: '194H — Commission' },
  { value: '194I', label: '194I — Rent' },
  { value: '194J', label: '194J — Professional fees' },
  { value: '194Q', label: '194Q — Purchase of goods' },
]

export interface LedgerAccount {
  id: string
  name: string
  group: LedgerGroup
  is_bank_or_cash: boolean
  is_active: boolean
  status: LedgerStatus
  proposal_reason: string
  row_count: number
  created_at: string
}

export type LedgerStatus = 'ACTIVE' | 'PROPOSED' | 'REJECTED'

export interface Party {
  id: string
  canonical_name: string
  alias_token: string
  gstin: string
  rcm_default: boolean
  tds_section: string
  is_active: boolean
  created_at: string
}

export interface Rule {
  id: string
  client: string | null
  ledger: string
  ledger_name: string
  party: string | null
  rcm: boolean
  tds_section: string
  match_type: string
  pattern: string
  direction: string
  priority: number
  confidence: number
  source: string
  is_active: boolean
  hit_count: number
  last_hit_at: string | null
  created_at: string
}

export interface JournalLine {
  id: string
  ledger_account: string
  ledger_name: string
  party: string | null
  party_name: string | null
  direction: 'DR' | 'CR'
  amount_paise: number
  amount_display: string
  rcm: boolean
  tds_section: string
}

export interface JournalEntry {
  id: string
  entry_no: number
  voucher_type: string
  entry_date: string
  financial_year: number
  fy_label: string
  narration: string
  total_paise: number
  total_display: string
  lines: JournalLine[]
  source_transaction: string | null
  supersedes: string | null
  superseded_by: string | null
  is_superseded: boolean
  approved_by: string | null
  approved_by_email: string | null
  approved_at: string
}

export interface ReportFooter {
  client_name: string
  financial_year: number
  fy_label: string
  period_start: string
  period_end: string
  entry_count: number
  pending_review: number
  is_complete: boolean
  generated_at: string
  caption: string
}

export interface LedgerBalance {
  name: string
  group: string
  opening_paise: number
  opening_display: string
  debit_paise: number
  debit_display: string
  credit_paise: number
  credit_display: string
  closing_debit_paise: number
  closing_debit_display: string
  closing_credit_paise: number
  closing_credit_display: string
}

export interface TrialBalance {
  rows: LedgerBalance[]
  total_debit_display: string
  total_credit_display: string
  balances: boolean
  footer: ReportFooter
}

export interface ProfitAndLoss {
  income: LedgerBalance[]
  expenses: LedgerBalance[]
  total_income_display: string
  total_expenses_display: string
  net_profit_paise: number
  net_profit_display: string
  footer: ReportFooter
}

export interface BalanceSheet {
  assets: LedgerBalance[]
  liabilities: LedgerBalance[]
  total_assets_display: string
  total_liabilities_display: string
  total_liabilities_and_profit_paise: number
  total_liabilities_and_profit_display: string
  net_profit_paise: number
  net_profit_display: string
  suspense_paise: number
  suspense_display: string
  balances: boolean
  footer: ReportFooter
}

export interface BalanceCheck {
  as_of: string
  ledger_balance_display: string
  statement_balance_display: string
  difference_paise: number
  difference_display: string
  matches: boolean
  can_close: boolean
  unapproved_count: number
  explanation: string
}

export interface TallyExport {
  xml: string
  voucher_count: number
  ledger_count: number
  unapproved: number
}

export interface Page<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

// --- GST reconciliation. Money here is paise only; format it with formatPaise. ---

export interface GstRegistration {
  id: string
  gstin: string
  state_code: string
  registration_type: string
}

export interface GstRunSummary {
  id: string
  registration: string
  gstin: string
  period_start: string
  status: 'draft' | 'signed_off'
}

export interface GstInvoiceRow {
  gstin: string
  invoice_no: string
  invoice_date: string | null
  supplier_name: string
  hsn: string
  section: string
  taxable_paise: number
  igst_paise: number
  cgst_paise: number
  sgst_paise: number
  cess_paise: number
}

export interface GstMatchRow {
  id: string
  itc_status: string
  eligible_paise: number
  ineligible_paise: number
  cause: string
  action: string
  timing: boolean
  differences: Record<string, number>
  book: GstInvoiceRow | null
  portal: GstInvoiceRow | null
  decision: { kind: string; note: string; at: string } | null
}

export interface GstGroup {
  kind: string
  title: string
  count: number
  rows: GstMatchRow[]
}

export interface GstRun {
  id: string
  registration: { id: string; gstin: string; state_code: string }
  period_start: string
  status: 'draft' | 'signed_off'
  signed_off_at: string | null
  has_register: boolean
  has_portal: boolean
  summary: {
    counts: Record<string, number>
    eligible_paise: number
    blocked_paise: number
    ineligible_paise: number
    rcm_liability_paise: number
    unclaimed_in_2b_paise: number
    unresolved: number
  }
  groups: GstGroup[]
  actions: { match: string; text: string }[]
  gstr3b: { code: string; label: string; igst_paise: number; cgst_paise: number; sgst_paise: number; cess_paise: number }[]
}
