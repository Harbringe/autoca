// One request for where every client's books stand: the source for the dashboard, the pipeline,
// the module landings and the clients list. Keyed under ['clients'] so anything that invalidates
// the clients (a post, a sign-off, a lead change) refreshes it too.

import { queryOptions } from '@tanstack/react-query'
import { raw } from '@/api/client'
import type { FirmOverview } from '@/api/types'
import { V1 } from './clients'

export const firmOverview = () =>
  queryOptions({
    queryKey: ['clients', 'overview'],
    queryFn: () => raw.get<FirmOverview>(`${V1}/firm/overview/`),
    staleTime: 15_000,
  })
