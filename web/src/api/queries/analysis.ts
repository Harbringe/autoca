// Cost centres, tagging journal lines to them, budgets, and the reports that read them.

import { queryOptions, useMutation } from '@tanstack/react-query'
import { raw } from '@/api/client'
import { allPages } from './books'
import { clientKeys, useInvalidateClient, V1 } from './clients'

const base = (clientId: string) => `${V1}/clients/${clientId}`

export interface CostCentre {
  id: string
  name: string
}

export const costCentres = (clientId: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'cost-centres'),
    queryFn: () => allPages<CostCentre>(`${base(clientId)}/cost-centres/`),
  })

export function useMakeCostCentre(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({ mutationFn: (name: string) => raw.post<CostCentre>(`${base(clientId)}/cost-centres/`, { name }), onSuccess: invalidate })
}

export function useRemoveCostCentre(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({ mutationFn: (id: string) => raw.delete(`${base(clientId)}/cost-centres/${id}/`), onSuccess: invalidate })
}

export interface Tag {
  line: string
  cost_centre: string
  cost_centre_name: string
  amount_paise: number
}

export const entryTags = (clientId: string, entry: string) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'cost-centre-tags', entry),
    queryFn: () => raw.get<Tag[]>(`${base(clientId)}/cost-centre-tags/`, { entry }),
  })

export function useTagLine(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (body: { line: string; allocations: { cost_centre: string; amount_paise: number }[] }) =>
      raw.post<Tag[]>(`${base(clientId)}/cost-centre-tags/`, body),
    onSuccess: invalidate,
  })
}

export interface CentreReport {
  fy: number
  centres: { id: string; name: string; income_paise: number; expense_paise: number; net_paise: number; ledgers: { ledger: string; is_income: boolean; amount_paise: number }[] }[]
  unallocated_income_paise: number
  unallocated_expense_paise: number
}

export const costCentreReport = (clientId: string, fy: number) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'reports', 'cost-centre-report', fy),
    queryFn: () => raw.get<CentreReport>(`${base(clientId)}/cost-centre-report/`, { fy }),
  })

export interface Variance {
  fy: number
  through: string | null
  ledgers: {
    ledger_id: string
    ledger: string
    is_income: boolean
    months: { month: string; budget_paise: number | null; actual_paise: number; variance_paise: number }[]
    budget_paise: number
    actual_paise: number
    variance_paise: number
  }[]
}

export const budgetVariance = (clientId: string, fy: number) =>
  queryOptions({
    queryKey: clientKeys.part(clientId, 'reports', 'budget-variance', fy),
    queryFn: () => raw.get<Variance>(`${base(clientId)}/budgets/variance/`, { fy }),
  })

export function useSetBudget(clientId: string) {
  const invalidate = useInvalidateClient(clientId)
  return useMutation({
    mutationFn: (body: { fy: number; ledger: string; months: Record<string, number | null> }) => raw.put<unknown>(`${base(clientId)}/budgets/set/`, body),
    onSuccess: invalidate,
  })
}
