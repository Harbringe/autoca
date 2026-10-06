// The reporting dashboards. The portfolio is keyed under ['clients'] so a post, a seal or a lead change
// refreshes it with the rest of the firm; a client's snapshot is keyed under that client for the same reason.

import { queryOptions } from '@tanstack/react-query'
import { raw } from '@/api/client'
import type { ClientSnapshot, Portfolio } from '@/api/types'
import { clientKeys, V1 } from './clients'

export const portfolio = () =>
  queryOptions({
    queryKey: ['clients', 'portfolio'],
    queryFn: () => raw.get<Portfolio>(`${V1}/firm/portfolio/`),
    staleTime: 30_000,
  })

export const clientSnapshot = (id: string, fy: number) =>
  queryOptions({
    queryKey: clientKeys.part(id, 'snapshot', fy),
    queryFn: () => raw.get<ClientSnapshot>(`${V1}/clients/${id}/dashboard/?fy=${fy}`),
    staleTime: 30_000,
  })
