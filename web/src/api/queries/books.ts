// Reads and writes for one client's books: the queue, the journal, masters, reports, sign-off.
//
// These go through the same transport as everything else (src/api/client.ts), typed with
// the backend's schema types. Lists are fetched whole (500 a page, every page): a client's
// year is a few hundred rows, and a screen that pages through its own books is a screen a
// CA cannot scan.

import { queryOptions, useMutation } from '@tanstack/react-query'
import { raw } from '@/api/client'
import type {
  BalanceCheck,
  BalanceSheet,
  Classification,
  EntryChange,
  InventoryReportData,
  JournalEntry,
  LedgerAccount,
  LedgerRow,
  Page,
  Party,
  ProfitAndLoss,
  Rule,
  Statements,
  StatementSettings,
  StatementTransaction,
  TrialBalance,
} from '@/api/types'
import { clientKeys, useInvalidateClient, V1 } from './clients'

/** Pages fetched at once after the first. A few at a time: quicker than one after another, and kind to the server and an old machine. */
const PAGES_AT_ONCE = 4

/**
 * Every page of a paginated list, as one array. The first page says how many there are, and the rest are then fetched a few at a time
 * instead of one after another, so a long list waits for the slowest page of each group, not for the sum of all of them.
 */
export async function allPages<T>(path: string, query: Record<string, string | number | boolean | undefined> = {}): Promise<T[]> {
  const get = (page: number) => raw.get<Page<T>>(path, { ...query, page, page_size: 500 })
  const first = await get(1)
  const rows: T[] = [...first.results]
  if (!first.next) return rows
  const pages = Math.max(2, Math.ceil(first.count / Math.max(first.results.length, 1)))
  for (let from = 2; from <= pages; from += PAGES_AT_ONCE) {
    const group = await Promise.all(Array.from({ length: Math.min(PAGES_AT_ONCE, pages - from + 1) }, (_, i) => get(from + i)))
    for (const page of group) rows.push(...page.results)
  }
  return rows
}

export type Stage = 'unresolved' | 'pending_approval' | 'all'
/** The review screen's tabs: the three queues of waiting rows, and what has already been posted. */
export type ReviewTab = Stage | 'posted'

export const reviewQueue = (clientId: string, stage: Stage) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'queue', stage),
    queryFn: () =>
      allPages<Classification>(`${V1}/clients/${clientId}/review-queue/`, { stage: stage === 'all' ? undefined : stage }),
  })

export const ledgers = (clientId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'ledgers'),
    queryFn: () => allPages<LedgerAccount>(`${V1}/clients/${clientId}/ledgers/`),
  })

/** Every row placed in one ledger, in any year, and whether each has been posted yet. */
export const ledgerRows = (clientId: string, ledgerId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'ledgers', ledgerId, 'rows'),
    queryFn: () => allPages<LedgerRow>(`${V1}/clients/${clientId}/ledgers/${ledgerId}/rows/`),
  })

export const parties = (clientId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'parties'),
    queryFn: () => allPages<Party>(`${V1}/clients/${clientId}/parties/`),
  })

export const rules = (clientId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'rules'),
    queryFn: () => allPages<Rule>(`${V1}/clients/${clientId}/rules/`),
  })

export const journal = (clientId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'journal'),
    queryFn: () => allPages<JournalEntry>(`${V1}/journal-entries/`, { client: clientId, live: true }),
  })

/** One financial year's live vouchers, for a screen that shows a single year (the Day Book): a client with many years does not load them all. */
export const journalYear = (clientId: string, fy: number) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'journal', 'fy', fy),
    queryFn: () => allPages<JournalEntry>(`${V1}/journal-entries/`, { client: clientId, live: true, financial_year: fy }),
  })

/** The financial years a client has vouchers in, without the vouchers. */
export const journalYears = (clientId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'journal', 'years'),
    queryFn: () => raw.get<number[]>(`${V1}/journal-entries/years/`, { client: clientId }),
  })

export const entryChanges = (clientId: string, entryId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'journal', entryId, 'changes'),
    queryFn: () => raw.get<EntryChange[]>(`${V1}/journal-entries/${entryId}/changes/`),
  })

/** One page of a statement's rows. The viewer shows a page at a time, so it asks for just that page and not the whole statement. */
export const statementRowsPage = (clientId: string, statementId: string, page: number, pageSize: number) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'statements', statementId, 'rows', page, pageSize),
    queryFn: () => raw.get<Page<StatementTransaction>>(`${V1}/clients/${clientId}/statements/${statementId}/transactions/`, { page, page_size: pageSize }),
  })

/** `godown` is a godown's id, or `none` for the main location; leave it out for the whole business. */
export const inventoryReport = (clientId: string, fy: number, godown?: string, asAt?: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'reports', 'inventory', fy, godown ?? 'all', asAt ?? 'year-end'),
    queryFn: () =>
      raw.get<InventoryReportData>(`${V1}/clients/${clientId}/reports/inventory/`, { fy, ...(godown ? { godown } : {}), ...(asAt ? { as_at: asAt } : {}) }),
  })

export interface StockCheck {
  key: string
  title: string
  status: 'ok' | 'attention' | 'info'
  message: string
  examples: string[]
}

export interface StockReconciliation {
  fy: number
  as_at: string
  register_value_paise: number
  books_value_paise: number
  difference_paise: number
  agrees: boolean
  checks: StockCheck[]
}

/** The stock register read against the books, the bills and the item list. Writes nothing. */
export const stockReconciliation = (clientId: string, fy: number) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'reports', 'stock-reconciliation', fy),
    queryFn: () => raw.get<StockReconciliation>(`${V1}/clients/${clientId}/reports/stock-reconciliation/`, { fy }),
  })

export interface GstTieOut {
  fy: number
  agrees: boolean
  heads: { side: 'output' | 'input'; head: string; invoices_paise: number; books_paise: number; difference_paise: number }[]
  months: Record<string, string | number>[]
  net: { output_paise: number; input_paise: number; payable_paise: number }
}

export const gstTieOut = (clientId: string, fy: number) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'reports', 'gst-tieout', fy),
    queryFn: () => raw.get<GstTieOut>(`${V1}/clients/${clientId}/reports/gst-tieout/`, { fy }),
  })

export type Gstr3bRow = { taxable_paise: number; igst_paise: number; cgst_paise: number; sgst_paise: number; cess_paise: number }
export type Gstr3bTax = Omit<Gstr3bRow, 'taxable_paise'>

export interface Gstr3b {
  month: string
  outward_taxable: Gstr3bRow
  zero_rated_paise: number
  exempt_nil_paise: number
  non_gst_outward_paise: number
  inward_reverse_charge: Gstr3bRow
  inward_exempt_paise: number
  itc_all_other: Gstr3bRow
  itc_reverse_charge: Gstr3bRow
  itc_reversed: Gstr3bTax
  opening_credit: Gstr3bTax
  liability: Gstr3bTax
  paid_by_credit: Gstr3bTax
  paid_in_cash: Gstr3bTax
  interest: Gstr3bTax
  late_fee_paise: number
  carry_forward: Gstr3bTax
  untaxed_sales_paise: number
  untaxed_unexplained_paise: number
  counts: { sales: number; purchases: number; reverse_charge: number }
  entries: Record<string, number | null>
}

export const gstr3b = (clientId: string, month: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'reports', 'gstr3b', month),
    queryFn: () => raw.get<Gstr3b>(`${V1}/clients/${clientId}/reports/gstr3b/`, { month }),
  })

export interface Gstr1Row {
  number: string
  date: string
  party: string
  gstin: string
  value_paise: number
  taxable_paise: number
  rate: string
  igst_paise: number
  cgst_paise: number
  sgst_paise: number
  cess_paise: number
}
export interface Gstr1Section {
  rows: Gstr1Row[]
  total: Record<string, number>
}
export interface Gstr1 {
  month: string
  b2b: Gstr1Section
  b2cl: Gstr1Section
  b2cs: { rows: { supply: string; rate: string; taxable_paise: number; igst_paise: number; cgst_paise: number; sgst_paise: number; cess_paise: number }[] }
  credit_notes_registered: Gstr1Section
  credit_notes_unregistered: Gstr1Section
  exempt_nil_non_gst: { zero_rated_paise: number; exempt_paise: number; non_gst_paise: number; untaxed_sales_paise: number }
  hsn: { hsn: string; unit: string; quantity: number; taxable_paise: number; igst_paise: number; cgst_paise: number; sgst_paise: number; cess_paise: number }[]
  hsn_bills_without_items: number
  documents: { label: string; from: string; to: string; count: number }[]
  agrees_with_3b: boolean
  taxable_in_tables_paise: number
  taxable_in_3b_paise: number
}

export interface Gstr1File {
  json: unknown
  missing: string[]
}

export const gstr1File = (clientId: string, month: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'reports', 'gstr1-file', month),
    queryFn: () => raw.get<Gstr1File>(`${V1}/clients/${clientId}/reports/gstr1/file/`, { month }),
    enabled: false,
  })

export const gstr1 = (clientId: string, month: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'reports', 'gstr1', month),
    queryFn: () => raw.get<Gstr1>(`${V1}/clients/${clientId}/reports/gstr1/`, { month }),
  })

export function useSaveGstr3bEntries(clientId: string, month: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (entries: Record<string, number | null>) => raw.put<Gstr3b>(`${V1}/clients/${clientId}/reports/gstr3b/?month=${month}`, entries),
    onSuccess: invalidate,
  })
}

export interface GroupLedger {
  ledger_id: string | null
  name: string
  opening_paise: number
  debit_paise: number
  credit_paise: number
  closing_paise: number
}
export interface GroupRow {
  group: string
  label: string
  opening_paise: number
  debit_paise: number
  credit_paise: number
  closing_paise: number
  ledgers: GroupLedger[]
}
export interface GroupSummary {
  fy: number
  groups: GroupRow[]
  total_debit_paise: number
  total_credit_paise: number
}
export interface LedgerMonthly {
  fy: number
  ledger: { id: string; name: string; group: string; group_label: string }
  opening_paise: number
  months: { month: string; debit_paise: number; credit_paise: number; closing_paise: number }[]
  total_debit_paise: number
  total_credit_paise: number
  closing_paise: number
}

/** Each group's year with the ledgers under it, read from the same balances as the Trial Balance. */
export const groupSummary = (clientId: string, fy: number) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'reports', 'group-summary', fy),
    queryFn: () => raw.get<GroupSummary>(`${V1}/clients/${clientId}/reports/group-summary/`, { fy }),
  })

/** One ledger through the twelve months of the year. */
export const ledgerMonthly = (clientId: string, fy: number, ledger: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'reports', 'ledger-monthly', fy, ledger),
    queryFn: () => raw.get<LedgerMonthly>(`${V1}/clients/${clientId}/reports/ledger-monthly/`, { fy, ledger }),
  })

export function useUseRegisterStock(clientId: string, fy: number) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: () => raw.post<StockReconciliation>(`${V1}/clients/${clientId}/reports/stock-reconciliation/use-register/?fy=${fy}`, {}),
    onSuccess: invalidate,
  })
}

export const trialBalance = (clientId: string, fy: number) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'reports', 'tb', fy),
    queryFn: () => raw.get<TrialBalance>(`${V1}/clients/${clientId}/reports/trial-balance/`, { fy }),
  })

export const profitAndLoss = (clientId: string, fy: number) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'reports', 'pl', fy),
    queryFn: () => raw.get<ProfitAndLoss>(`${V1}/clients/${clientId}/reports/profit-and-loss/`, { fy }),
  })

export const balanceSheet = (clientId: string, fy: number) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'reports', 'bs', fy),
    queryFn: () => raw.get<BalanceSheet>(`${V1}/clients/${clientId}/reports/balance-sheet/`, { fy }),
  })

export const reconciliation = (clientId: string, accountId: string, asOf: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'reconciliation', accountId, asOf),
    queryFn: () => raw.get<BalanceCheck>(`${V1}/bank-accounts/${accountId}/reconciliation/`, { as_of: asOf }),
    retry: false,
  })

/** The Balance Sheet and Statement of Profit and Loss in the ICAI non-corporate format, with the previous year and the notes. */
export const financialStatements = (clientId: string, fy: number) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'financial-statements', fy),
    queryFn: () => raw.get<Statements>(`${V1}/clients/${clientId}/reports/financial-statements/`, { fy }),
  })

/** What the statements need that no ledger holds: Notes 1 and 2, rounding, and each year's closing stock and partners. */
export const statementSettings = (clientId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'financial-statements', 'settings'),
    queryFn: () => raw.get<StatementSettings>(`${V1}/clients/${clientId}/reports/financial-statements/settings/`),
  })
