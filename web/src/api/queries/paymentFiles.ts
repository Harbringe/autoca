// Where to pay a party, and the bank payment file built from what the client owes.

import { queryOptions, useMutation } from '@tanstack/react-query'
import { raw } from '@/api/client'
import { clientKeys, useInvalidateClient, V1 } from './clients'

export interface Payable {
  party: string
  name: string
  open_paise: number
  bills: number
  ready: boolean
  account_last4: string
}

export const payables = (clientId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'payment-files'),
    queryFn: () => raw.get<Payable[]>(`${V1}/clients/${clientId}/payment-files/`),
  })

export function useSavePaymentDetails(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: ({ party, ...body }: { party: string; account_number: string; ifsc: string; account_name: string }) =>
      raw.put<unknown>(`${V1}/clients/${clientId}/parties/${party}/payment-details/`, body),
    onSuccess: invalidate,
  })
}

export interface PaymentFileRequest {
  bank_account: string
  mode: 'NEFT' | 'RTGS' | 'IMPS'
  payment_date: string
  items: { party: string; amount_paise: number; narration?: string }[]
}

export function useMakePaymentFile(clientId: string) {
  return useMutation({
    mutationFn: (body: PaymentFileRequest) => raw.postBlob(`${V1}/clients/${clientId}/payment-files/`, body),
  })
}
