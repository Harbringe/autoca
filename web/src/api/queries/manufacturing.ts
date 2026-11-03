// Bills of materials and production runs.

import { queryOptions, useMutation } from '@tanstack/react-query'
import { raw } from '@/api/client'
import { allPages } from './books'
import { clientKeys, useInvalidateClient, V1 } from './clients'

const base = (clientId: string) => `${V1}/clients/${clientId}/boms/`

export interface BomComponent {
  name: string
  unit: string
  quantity: string
}

export interface Bom {
  id: string
  name: string
  unit: string
  output_quantity: string
  components: BomComponent[]
}

export const boms = (clientId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'boms'),
    queryFn: () => allPages<Bom>(base(clientId)),
  })

export function useMakeBom(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (body: { name: string; unit: string; output_quantity: string; components: BomComponent[] }) => raw.post<Bom>(base(clientId), body),
    onSuccess: invalidate,
  })
}

export function useRemoveBom(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({ mutationFn: (id: string) => raw.delete(`${base(clientId)}${id}/`), onSuccess: invalidate })
}

export interface RunPlan {
  quantity: string
  components: { name: string; unit: string; needed: string; available: string; cost_paise: number; enough: boolean }[]
  cost_paise: number
  short: string[]
}

export const runPlan = (clientId: string, bom: string, quantity: string, date: string, godown = '') =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'boms', bom, 'plan', quantity, date, godown),
    queryFn: () => raw.get<RunPlan>(`${base(clientId)}${bom}/plan/`, godown ? { quantity, date, godown } : { quantity, date }),
    enabled: !!quantity && Number(quantity) > 0,
  })

export function useProduce(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: ({ bom, ...body }: { bom: string; quantity: string; entry_date: string; extra_cost_paise: number; note: string; godown?: string | null }) =>
      raw.post<unknown>(`${base(clientId)}${bom}/produce/`, body),
    onSuccess: invalidate,
  })
}
