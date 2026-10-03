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
  JournalEntry,
  LedgerAccount,
  LedgerRow,
  Page,
  Party,
  ProfitAndLoss,
  Rule,
  StatementTransaction,
  TrialBalance,
} from '@/api/types'
import { clientKeys, V1 } from './clients'

/** Every page of a paginated list, as one array. */
export async function allPages<T>(path: string, query: Record<string, string | number | boolean | undefined> = {}): Promise<T[]> {
  const rows: T[] = []
  for (let page = 1; ; page += 1) {
    const result = await raw.get<Page<T>>(path, { ...query, page, page_size: 500 })
    rows.push(...result.results)
    if (!result.next) return rows
  }
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

export const statementRows = (clientId: string, statementId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'statements', statementId, 'rows'),
    queryFn: () => allPages<StatementTransaction>(`${V1}/clients/${clientId}/statements/${statementId}/transactions/`),
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
