import { describe, expect, it } from 'vitest'
import type { AttentionItem, PortfolioClient } from '@/api/types'
import { actionsFor, clientHealth, dueWithin, groupAttention, healthCounts, layoutFor, sealingFigures } from './dashboard'

const base = {
  id: 'c1',
  name: 'Acme',
  lead: null,
  stage: 'needs_ledger',
  next_step: { code: 'place', label: '', count: 4 },
  unresolved: 0,
  pending_approval: 0,
  assistant_waiting: 0,
  ai_unchecked: 0,
  review_pending: false,
  signed_off_through: null,
  last_statement_end: null,
  months_missing: [],
  detail: true,
  health: 'on_track',
} as unknown as PortfolioClient
const row = (extra: Partial<PortfolioClient>): PortfolioClient => ({ ...base, ...extra }) as PortfolioClient

describe('layoutFor', () => {
  it('maps roles to layouts', () => {
    expect(layoutFor('FIRM_ADMIN')).toBe('owner')
    expect(layoutFor('READ_ONLY')).toBe('owner')
    expect(layoutFor('SENIOR_CA')).toBe('senior')
    expect(layoutFor('STAFF')).toBe('staff')
  })
  it('gives the least privileged layout to anything unknown', () => {
    expect(layoutFor(null)).toBe('staff')
    expect(layoutFor(undefined)).toBe('staff')
    expect(layoutFor('SOMETHING_NEW')).toBe('staff')
  })
})

describe('clientHealth', () => {
  it('takes the server health and explains it in words', () => {
    expect(clientHealth(row({}))).toEqual({ health: 'on_track', reasons: [] })
    expect(clientHealth(row({ health: 'overdue', tds_overdue_paise: 4250000 })).reasons[0]).toContain('TDS')
    expect(clientHealth(row({ health: 'at_risk', months_missing: ['2026-07'] })).reasons).toEqual(['1 statement month missing'])
    expect(clientHealth(row({ health: 'at_risk', failing_controls: 2 })).reasons).toEqual(['2 checks failing'])
  })
  it('counts every client once by the server health', () => {
    const counts = healthCounts([row({}), row({ health: 'at_risk', failing_controls: 1 }), row({ health: 'overdue', seal_due: '2026-09-30', months_missing: ['2026-07'] })])
    expect(counts).toMatchObject({ total: 3, onTrack: 1, atRisk: 1, overdue: 1, sealLate: 1, monthsLate: 1, tdsLate: 0 })
  })
})

describe('sealingFigures', () => {
  it('counts ready-to-seal books and finds the oldest wait', () => {
    expect(sealingFigures([row({ ready_to_seal: true }), row({ oldest_pending_approval_days: 4 }), row({ oldest_pending_approval_days: 9 }), row({})])).toEqual({ readyToSeal: 1, waitingForApproval: 2, oldestDays: 9 })
  })
})

describe('actionsFor', () => {
  it('puts late work first, then sign-off before the rest, and skips clients with nothing to do', () => {
    const list = actionsFor([
      row({ id: 'a', name: 'Zed', next_step: { code: 'place', label: '', count: 1 } }),
      row({ id: 'b', name: 'Bee', next_step: { code: 'sign_off', label: '', count: 0 } }),
      row({ id: 'c', name: 'Cee', next_step: { code: 'none', label: '', count: 0 } }),
      row({ id: 'd', name: 'Dee', next_step: { code: 'upload', label: '', count: 0 }, seal_due: '2026-09-30', health: 'overdue' }),
    ])
    expect(list.map((a) => a.clientId)).toEqual(['d', 'b', 'a'])
    expect(list[2]!.title).toBe('Sort 1 entry into accounts')
  })
})

describe('dueWithin', () => {
  it('keeps dates up to and including the last day', () => {
    const rows = [{ date: '2026-10-07' }, { date: '2026-11-06' }, { date: '2026-11-07' }]
    expect(dueWithin(rows, 30, new Date(2026, 9, 7)).map((r) => r.date)).toEqual(['2026-10-07', '2026-11-06'])
  })
})

describe('groupAttention', () => {
  const item = (client: string, severity: AttentionItem['severity'], text: string) =>
    ({ client, client_name: client.toUpperCase(), severity, text, kind: 'k', to: `/clients/${client}`, search: {}, amount_paise: null, amount_display: null }) as AttentionItem
  it('makes one row per client, critical first, then most items', () => {
    const rows = groupAttention([item('b', 'medium', 'm1'), item('b', 'high', 'h1'), item('a', 'critical', 'c1'), item('c', 'medium', 'm2'), item('c', 'medium', 'm3'), item('c', 'medium', 'm4')])
    expect(rows.map((r) => r.clientId)).toEqual(['a', 'c', 'b'])
    expect(rows[2]).toMatchObject({ items: 2, text: 'h1', others: 1, critical: 0 })
  })
})
