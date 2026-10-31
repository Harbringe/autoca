// Importing a client's history from Tally: upload a vouchers export, look at the preview, post it, or take it back.
//
// Posting or undoing writes entries, bills and parties, so a success marks everything about the client stale (the same prefix
// every other change to the books uses), not one list.

import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { raw } from '@/api/client'
import { useInvalidateClient, V1 } from './clients'

export interface VoucherRunRow {
  ordinal: number
  type: string
  number: string
  date: string
  party: string
  total_paise: number
  action: 'post' | 'skip'
  bill: boolean
  reason: string
  note: string
}

export interface VoucherRun {
  id: string
  status: 'PREVIEW' | 'CONFIRMED' | 'DISCARDED'
  financial_year: number
  counts: {
    vouchers: number
    will_post: number
    will_make_bill: number
    skipped: number
    bank_waiting: number
    bank_rows: number
    stock_lines: number
    by_type: Record<string, number>
    unknown_types?: Record<string, number>
    type_map?: Record<string, string>
    existing_entries?: number
    existing_statement_rows?: number
    date_from: string
    date_to: string
  }
  rows: VoucherRunRow[]
  result: { posted?: number; bills?: number; skipped?: number; failed?: { guid: string; reason: string }[]; bank_rows?: number; unmatched_bills?: number; rules_learned?: number; stock_entries?: number; undone?: number } | null
  expires_at: string
  created_at: string
  /** The file as uploaded; it stays with the client's documents. */
  file_name: string
  document: string | null
  uploaded_by_name: string
  /** A worker is writing the vouchers now. */
  posting: boolean
  progress: { done: number; total: number } | null
  error: string
}

export type VoucherRunSummary = Omit<VoucherRun, 'rows'>

const base = (clientId: string) => `${V1}/clients/${clientId}/tally-imports`

// ---- The chart of accounts and opening balances (the masters export) ----

export interface MastersRow {
  row: number
  name: string
  tally_group: string
  our_group: string | null
  opening_paise: number
  opening_display: string
  action: 'create' | 'match' | 'conflict' | 'needs_group' | 'skipped'
  reason: string
  ledger_name: string | null
  conflict: { kind: string; choices: string[]; default: string | null } | null
  bank: { label: string; status: 'propose' | 'agree' | 'conflict' | 'nothing'; choices: string[]; default: string | null; ours_paise: number | null; tally_paise: number } | null
}

export interface MastersRun {
  id: string
  status: 'PREVIEW' | 'CONFIRMED' | 'DISCARDED'
  financial_year: number
  counts: { create: number; match: number; conflict: number; needs_group: number; skipped: number; with_opening: number; bank_conflicts: number; difference_display: string }
  rows: MastersRow[]
  result: { created: number; matched: number; renamed: number; regrouped: number; openings: number; bank_openings: number; skipped: number; difference_display: string } | null
}

export interface Resolution {
  row: number
  choice?: string
  group?: string
  bank?: string
}

export function useStageMasters(clientId: string) {
  return useMutation({
    mutationFn: ({ file, financialYear, includeOpenings }: { file: File; financialYear: number; includeOpenings: boolean }) => {
      const form = new FormData()
      form.append('file', file)
      form.append('financial_year', String(financialYear))
      form.append('include_openings', String(includeOpenings))
      return raw.post<MastersRun>(`${base(clientId)}/`, form)
    },
  })
}

export function useConfirmMasters(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: ({ runId, resolutions }: { runId: string; resolutions: Resolution[] }) =>
      raw.post<MastersRun>(`${base(clientId)}/${runId}/confirm/`, { resolutions }),
    onSuccess: invalidate,
  })
}

// ---- Vouchers ----

export function useStageVouchers(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tally-voucher-runs', clientId] }),
    mutationFn: ({ file, voucherTypes }: { file: File; voucherTypes?: Record<string, string> }) => {
      const form = new FormData()
      form.append('file', file)
      if (voucherTypes && Object.keys(voucherTypes).length) form.append('voucher_types', JSON.stringify(voucherTypes))
      return raw.post<VoucherRun>(`${base(clientId)}/vouchers/`, form)
    },
  })
}

/** The queue: every vouchers import of the client, newest first, without the voucher rows. */
export const voucherRuns = (clientId: string) =>
  queryOptions({
    queryKey: ['tally-voucher-runs', clientId],
    queryFn: () => raw.get<VoucherRunSummary[]>(`${base(clientId)}/voucher-runs/`),
  })

export const voucherRun = (clientId: string, runId: string) =>
  queryOptions({
    queryKey: ['tally-voucher-run', clientId, runId],
    queryFn: () => raw.get<VoucherRun>(`${base(clientId)}/${runId}/voucher-run/`),
  })

/** Queue the posting: the vouchers are written by a worker, so this answers at once and the run's progress is read afterwards. */
export function useConfirmVouchers(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ runId, allowOverlap }: { runId: string; allowOverlap?: boolean }) =>
      raw.post<VoucherRun>(`${base(clientId)}/${runId}/confirm-vouchers/`, { allow_overlap: !!allowOverlap }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tally-voucher-runs', clientId] }),
  })
}

export function useRefreshVoucherRun(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ runId, voucherTypes }: { runId: string; voucherTypes?: Record<string, string> }) =>
      raw.post<VoucherRun>(`${base(clientId)}/${runId}/refresh-vouchers/`, voucherTypes ? { voucher_types: voucherTypes } : {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tally-voucher-runs', clientId] }),
  })
}

export function useDiscardVoucherRun(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (runId: string) => raw.post<VoucherRun>(`${base(clientId)}/${runId}/discard/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tally-voucher-runs', clientId] }),
  })
}

export function useUndoVouchers(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (runId: string) => raw.post<VoucherRun>(`${base(clientId)}/${runId}/undo/`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tally-voucher-runs', clientId] })
      return invalidate()
    },
  })
}

// ---- Setting a client up from the files: ledgers and bank accounts ----

export interface LedgerProposal {
  name: string
  group: string
  reason: string
  uses: number
  unsure: boolean
}

export interface AccountProposal {
  ledger: string
  kind: 'BANK' | 'LOAN' | 'CARD'
  bank_code: string
  account_number: string
}

export interface Discovery {
  vouchers: number
  voucher_files: number
  master_files: number
  ignored: { file: string; reason: string }[]
  reports: { file: string; ledger: string; rows: number; left_out: number }[]
  ledgers: LedgerProposal[]
  accounts: AccountProposal[]
}

export interface SetupResult {
  ledgers: number
  accounts: number
  waiting_for_a_number: string[]
}

export function useDiscover(clientId: string) {
  return useMutation({
    mutationFn: ({ files, bankLedgers }: { files: File[]; bankLedgers: Record<string, string> }) => {
      const form = new FormData()
      for (const file of files) form.append('files', file)
      if (Object.keys(bankLedgers).length) form.append('bank_ledgers', JSON.stringify(bankLedgers))
      return raw.post<Discovery>(`${base(clientId)}/discover/`, form)
    },
  })
}

export function useSetup(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (body: { ledgers: { name: string; group: string }[]; accounts: AccountProposal[] }) =>
      raw.post<SetupResult>(`${base(clientId)}/setup/`, body),
    onSuccess: invalidate,
  })
}

// ---- Bank ledger reports ----

export function useStageBankReports(clientId: string) {
  return useMutation({
    mutationFn: ({ reports }: { reports: { file: File; account: string }[] }) => {
      const form = new FormData()
      for (const r of reports) {
        form.append('files', r.file)
        form.append('accounts', r.account)
      }
      return raw.post<VoucherRun>(`${base(clientId)}/bank-report/`, form)
    },
  })
}
