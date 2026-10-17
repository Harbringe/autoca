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
