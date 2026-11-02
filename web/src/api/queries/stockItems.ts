// The client's stock items: the master list kept by a person. Purchases and sales name the same items on their invoice lines.

import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { raw } from '@/api/client'
import { allPages } from './books'
import { V1 } from './clients'

export interface StockItem {
  id: string
  name: string
  unit: string
  hsn_sac: string
  gst_rate: string | null
  reorder_level: string | null
  purchase_ledger: string | null
  purchase_ledger_name: string
  sales_ledger: string | null
  sales_ledger_name: string
  aliases?: string[]
}

export type StockItemInput = Partial<Pick<StockItem, 'name' | 'unit' | 'hsn_sac' | 'gst_rate' | 'reorder_level' | 'purchase_ledger' | 'sales_ledger' | 'aliases'>>

const base = (clientId: string) => `${V1}/clients/${clientId}/stock-items/`

export const stockItems = (clientId: string) =>
  queryOptions({
    queryKey: ['stock-items', clientId],
    queryFn: () => allPages<StockItem>(base(clientId)),
  })

export function useMakeStockItem(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: StockItemInput) => raw.post<StockItem>(base(clientId), input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: stockItems(clientId).queryKey }),
  })
}

export function useChangeStockItem(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: StockItemInput }) => raw.patch<StockItem>(`${base(clientId)}${id}/`, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: stockItems(clientId).queryKey }),
  })
}

export function useRemoveStockItem(clientId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => raw.delete(`${base(clientId)}${id}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: stockItems(clientId).queryKey }),
  })
}
