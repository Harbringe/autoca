// The cheque register: cheques issued and received, post-dated ones, and their status.

import { queryOptions, useMutation } from '@tanstack/react-query'
import { raw } from '@/api/client'
import { allPages } from './books'
import { clientKeys, useInvalidateClient, V1 } from './clients'

const base = (clientId: string) => `${V1}/clients/${clientId}/cheques/`

export type ChequeStatus = 'PENDING' | 'CLEARED' | 'BOUNCED' | 'CANCELLED'

export interface Cheque {
  id: string
  bank_account: string
  bank_label: string
  direction: 'ISSUED' | 'RECEIVED'
  number: string
  cheque_date: string
  issued_on: string
  amount_paise: number
  party: string | null
  party_name: string
  payee_name: string
  print_name: string
  status: ChequeStatus
  status_display: string
  status_on: string | null
  note: string
  is_post_dated: boolean
  is_stale: boolean
}

export const cheques = (clientId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'cheques'),
    queryFn: () => allPages<Cheque>(base(clientId)),
  })

export const chequeAccounts = (clientId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'cheques', 'accounts'),
    queryFn: () => raw.get<{ id: string; label: string }[]>(`${base(clientId)}accounts/`),
  })

export interface Pdc {
  issued_paise: number
  received_paise: number
  by_month: { month: string; issued_paise: number; received_paise: number }[]
  due_soon: Cheque[]
  stale: Cheque[]
}

export const pdcSummary = (clientId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'cheques', 'pdc'),
    queryFn: () => raw.get<Pdc>(`${base(clientId)}pdc/`),
  })

export interface ChequeInput {
  bank_account: string
  direction: 'ISSUED' | 'RECEIVED'
  number: string
  cheque_date: string
  amount_paise: number
  payee_name: string
}

export function useAddCheque(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({ mutationFn: (body: ChequeInput) => raw.post<Cheque>(base(clientId), body), onSuccess: invalidate })
}

export function useSetChequeStatus(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: ChequeStatus }) => raw.post<Cheque>(`${base(clientId)}${id}/status/`, { status }),
    onSuccess: invalidate,
  })
}

export function useRemoveCheque(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({ mutationFn: (id: string) => raw.delete(`${base(clientId)}${id}/`), onSuccess: invalidate })
}

export const cheque = (clientId: string, id: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'cheques', id),
    queryFn: () => raw.get<Cheque>(`${base(clientId)}${id}/`),
  })
