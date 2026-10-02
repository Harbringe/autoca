// The measured figures (automation, accuracy, estimated time saved, what needs attention, turnaround).
// Only administrators and Senior CAs may ask; anyone else gets a 403 that the screens treat as "not for you".

import { queryOptions } from '@tanstack/react-query'
import { raw } from '@/api/client'
import type { FirmMetrics } from '@/api/types'
import { V1 } from './clients'
import type { DateRange } from './team'

export const firmMetrics = (range: DateRange) =>
  queryOptions({
    queryKey: ['firm', 'metrics', range.from, range.to],
    queryFn: () => raw.get<FirmMetrics>(`${V1}/firm/metrics/`, { from: range.from, to: range.to }),
    retry: false,
    staleTime: 30_000,
  })
