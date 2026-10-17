// Importing a client's history from Tally: upload a vouchers export, look at the preview, post it, or take it back.
//
// Posting or undoing writes entries, bills and parties, so a success marks everything about the client stale (the same prefix
// every other change to the books uses), not one list.

import { useMutation } from '@tanstack/react-query'
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
    by_type: Record<string, number>
    date_from: string
    date_to: string
  }
  rows: VoucherRunRow[]
  result: { posted?: number; bills?: number; skipped?: number; failed?: { guid: string; reason: string }[]; undone?: number } | null
  expires_at: string
}

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
  return useMutation({
    mutationFn: ({ file }: { file: File }) => {
      const form = new FormData()
      form.append('file', file)
      return raw.post<VoucherRun>(`${base(clientId)}/vouchers/`, form)
    },
  })
}

export function useConfirmVouchers(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (runId: string) => raw.post<VoucherRun>(`${base(clientId)}/${runId}/confirm-vouchers/`),
    onSuccess: invalidate,
  })
}

export function useUndoVouchers(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (runId: string) => raw.post<VoucherRun>(`${base(clientId)}/${runId}/undo/`),
    onSuccess: invalidate,
  })
}
