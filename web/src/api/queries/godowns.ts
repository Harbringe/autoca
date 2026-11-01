// Godowns (places the client keeps stock), moving stock between them, and booking a physical count.

import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { raw } from '@/api/client'
import { allPages } from './books'
import { useInvalidateClient, V1 } from './clients'

export interface Godown {
  id: string
  name: string
}

export interface StockCountResult {
  book_quantity: string
  counted_quantity: string
  difference: string
  entry: { id: string; direction: 'IN' | 'OUT'; quantity: string } | null
}

const base = (clientId: string) => `${V1}/clients/${clientId}`

export const godowns = (clientId: string) =>
  queryOptions({
    queryKey: ['godowns', clientId],
    queryFn: () => allPages<Godown>(`${base(clientId)}/godowns/`),
  })

export function useMakeGodown(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (name: string) => raw.post<Godown>(`${base(clientId)}/godowns/`, { name }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: godowns(clientId).queryKey }),
  })
}

export function useRemoveGodown(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => raw.delete(`${base(clientId)}/godowns/${id}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: godowns(clientId).queryKey }),
  })
}

export interface TransferInput {
  entry_date: string
  name: string
  unit?: string
  quantity: string
  from_godown: string | null
  to_godown: string | null
  note?: string
}

export function useTransferStock(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (input: TransferInput) => raw.post<{ entries: unknown[] }>(`${base(clientId)}/stock-entries/transfer/`, input),
    onSuccess: invalidate,
  })
}

export interface CountInput {
  entry_date: string
  name: string
  unit?: string
  counted_quantity: string
  godown?: string | null
  note?: string
}

export function useCountStock(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (input: CountInput) => raw.post<StockCountResult>(`${base(clientId)}/stock-entries/count/`, input),
    onSuccess: invalidate,
  })
}
