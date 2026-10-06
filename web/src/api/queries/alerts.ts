// Alerts, computed on the server from the books. Keyed under ['clients'] so a post, a seal or a fix
// refreshes them along with the rest of the firm; the bell also looks again every minute.

import { queryOptions } from '@tanstack/react-query'
import { raw } from '@/api/client'
import type { AlertFeed, AlertModule } from '@/api/types'
import { clientKeys, V1 } from './clients'

const suffix = (module?: AlertModule) => (module ? `?module=${module}` : '')

export const firmAlerts = (module?: AlertModule) =>
  queryOptions({
    queryKey: ['clients', 'alerts', module ?? 'all'],
    queryFn: () => raw.get<AlertFeed>(`${V1}/firm/alerts/${suffix(module)}`),
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  })

export const clientAlerts = (id: string, module?: AlertModule) =>
  queryOptions({
    queryKey: clientKeys.part(id, 'alerts', module ?? 'all'),
    queryFn: () => raw.get<AlertFeed>(`${V1}/clients/${id}/alerts/${suffix(module)}`),
    staleTime: 30_000,
  })
