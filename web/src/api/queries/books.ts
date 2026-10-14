// Reads and writes for one client's books: the queue, the journal, masters, reports, sign-off.
//
// These go through the same transport as everything else (src/api/client.ts), typed with
// the backend's schema types. Lists are fetched whole (500 a page, every page): a client's
// year is a few hundred rows, and a screen that pages through its own books is a screen a
// CA cannot scan.

import { queryOptions } from '@tanstack/react-query'
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
import { clientKeys, V1 } from './clients'

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

export const inventoryReport = (clientId: string, fy: number) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'reports', 'inventory', fy),
    queryFn: () => raw.get<InventoryReportData>(`${V1}/clients/${clientId}/reports/inventory/`, { fy }),
  })

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
