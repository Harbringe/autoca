// The audit trail of a client's books: changes to vouchers and to ledgers, parties and rules, newest first.

import { keepPreviousData, queryOptions } from '@tanstack/react-query'
import { raw } from '@/api/client'
import { V1 } from './clients'

export type ChangeKind = 'ENTRY' | 'LEDGER' | 'PARTY' | 'RULE' | 'SETTING' | 'ITEM'

export interface AuditRow {
  id: string
  at: string
  kind: ChangeKind
  action: string
  action_display: string
  label: string
  actor_name: string
  note: string
  before: Record<string, unknown>
  after: Record<string, unknown>
}

export interface AuditFilters {
  kind: '' | ChangeKind
  q: string
  from: string
  to: string
  offset: number
  limit: number
}

export const auditTrail = (clientId: string, f: AuditFilters) => {
  const query = new URLSearchParams()
  if (f.kind) query.set('kind', f.kind)
  if (f.q.trim()) query.set('q', f.q.trim())
  if (f.from) query.set('from', f.from)
  if (f.to) query.set('to', f.to)
  query.set('limit', String(f.limit))
  query.set('offset', String(f.offset))
  return queryOptions({
    queryKey: ['audit-trail', clientId, f],
    queryFn: () => raw.get<{ count: number; results: AuditRow[] }>(`${V1}/clients/${clientId}/audit-trail/?${query}`),
    placeholderData: keepPreviousData,
  })
}
