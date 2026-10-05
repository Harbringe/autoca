// Purchase and sales vouchers, as the bills they book.
//
// Posting or removing a voucher changes more than the bills list: the Day Book gains or loses an entry, the party gains
// its account, and the open items and reports move. So a successful change marks everything about the client stale (the
// same prefix every other change to the books uses) instead of patching one list, which is how two screens come to
// disagree about the same voucher.

import { queryOptions, useMutation } from '@tanstack/react-query'
import { raw } from '@/api/client'
import type { Bill, BillCreateRequest, BillDetail, SettlementContext } from '@/api/types'
import { allPages } from './books'
import { clientKeys, useInvalidateClient, V1 } from './clients'

export interface BillFilters {
  kind?: string
  party?: string
  status?: 'open' | 'settled'
  fy?: number
  q?: string
}

export const bills = (clientId: string, filters: BillFilters = {}) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'bills', filters),
    queryFn: () => allPages<Bill>(`${V1}/clients/${clientId}/bills/`, { ...filters }),
  })

export const bill = (clientId: string, billId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'bills', billId),
    queryFn: () => raw.get<BillDetail>(`${V1}/clients/${clientId}/bills/${billId}/`),
  })

/** The party's open bills for a payment on its account, and how the payment would clear them: only a suggestion. */
export const rowSettlement = (clientId: string, classificationId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'settlement', classificationId),
    queryFn: () => raw.get<SettlementContext>(`${V1}/classifications/${classificationId}/settlement/`),
  })

export function usePostBill(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (body: BillCreateRequest) => raw.post<BillDetail>(`${V1}/clients/${clientId}/bills/`, body),
    onSuccess: invalidate,
  })
}

export function useRemoveBill(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) =>
      raw.post<void>(`${V1}/clients/${clientId}/bills/${id}/remove/`, { note }),
    onSuccess: invalidate,
  })
}
