// The audit log, read-only. Plain Django view, so the row shape is in api/types.ts.

import { keepPreviousData, queryOptions } from '@tanstack/react-query'
import { raw } from '@/api/client'
import type { AuditRow, Page } from '@/api/types'
import { V1 } from './clients'

export const AUDIT_PAGE = 25

export const auditLog = (page: number, failedOnly: boolean) =>
  queryOptions({
    queryKey: ['audit', page, failedOnly],
    queryFn: () => raw.get<Page<AuditRow>>(`${V1}/audit/`, { page, page_size: AUDIT_PAGE, failed: failedOnly ? 'true' : undefined }),
    placeholderData: keepPreviousData,
  })
