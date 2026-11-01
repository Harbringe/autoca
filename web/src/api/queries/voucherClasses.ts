// Voucher classes: a preset head ledger and GST rate for a sales or purchase voucher. Choosing one only fills the form in.

import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { raw } from '@/api/client'
import { allPages } from './books'
import { V1 } from './clients'

export interface VoucherClass {
  id: string
  name: string
  voucher_type: 'Sales' | 'Purchase'
  type_name: string
  head_ledger: string
  head_ledger_name: string
  gst_rate: string | null
}

export type VoucherClassInput = Pick<VoucherClass, 'name' | 'voucher_type' | 'head_ledger'> & { type_name?: string; gst_rate?: string | null }

const base = (clientId: string) => `${V1}/clients/${clientId}/voucher-classes/`

export const voucherClasses = (clientId: string) =>
  queryOptions({
    queryKey: ['voucher-classes', clientId],
    queryFn: () => allPages<VoucherClass>(base(clientId)),
  })

export function useMakeVoucherClass(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: VoucherClassInput) => raw.post<VoucherClass>(base(clientId), input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: voucherClasses(clientId).queryKey }),
  })
}

export function useRemoveVoucherClass(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => raw.delete(`${base(clientId)}${id}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: voucherClasses(clientId).queryKey }),
  })
}
