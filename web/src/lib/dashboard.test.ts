import { describe, expect, it } from 'vitest'
import type { AttentionItem, PortfolioClient } from '@/api/types'
import { actionsFor, booksInReview, clientHealth, dueWithin, groupAttention, healthCounts, layoutFor, lateNote, riskNote, sealingFigures, standingContext, workWaiting } from './dashboard'

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

const TODAY = new Date(2026, 9, 11) // 11-10-2026

describe('clientHealth', () => {
  const ctx = { today: TODAY }
  it('is on track when nothing is late, no date is within 7 days and no month is missing', () => {
    expect(clientHealth(row({}), ctx)).toEqual({ health: 'on_track', reasons: [], watch: [] })
    expect(clientHealth(row({ next_seal_date: '2026-10-19' }), ctx).health).toBe('on_track')
  })
  it('is late when a seal date has passed unsealed or TDS is past its deposit date, whatever the server says', () => {
    expect(clientHealth(row({ health: 'at_risk', seal_due: '2026-09-30' }), ctx)).toMatchObject({ health: 'overdue', reasons: ['Seal date passed (30-09-2026)'] })
    expect(clientHealth(row({ tds_overdue_paise: 4250000 }), ctx).reasons[0]).toContain('TDS')
  })
  it('is at risk for a missing month or a date within 7 days, today included', () => {
    expect(clientHealth(row({ months_missing: ['2026-07'] }), ctx)).toMatchObject({ health: 'at_risk', reasons: ['1 statement month missing'] })
    expect(clientHealth(row({ next_seal_date: '2026-10-18' }), ctx).health).toBe('at_risk')
    expect(clientHealth(row({ next_seal_date: '2026-10-11' }), ctx).health).toBe('at_risk')
    expect(clientHealth(row({ next_seal_date: '2026-10-10' }), ctx).health).toBe('on_track')
  })
  it('uses an unpaid TDS deposit falling due within 7 days', () => {
    const tdsDue = new Map([['c1', ['2026-10-15']]])
    expect(clientHealth(row({}), { ...ctx, tdsDue })).toMatchObject({ health: 'at_risk', reasons: ['TDS deposit due 15-10-2026'] })
  })
  it('lists failing checks beside the standing without changing it', () => {
    expect(clientHealth(row({ failing_controls: 2, blocking_unexplained: 1 }), ctx)).toEqual({ health: 'on_track', reasons: [], watch: ['2 checks failing', '1 item blocking the seal'] })
  })
  it('puts late before at risk and lists every cause', () => {
    const h = clientHealth(row({ seal_due: '2026-09-30', months_missing: ['2026-07'] }), ctx)
    expect(h.health).toBe('overdue')
    expect(h.reasons).toEqual(['Seal date passed (30-09-2026)', '1 statement month missing'])
  })
  it('counts every client once by the derived standing', () => {
    const counts = healthCounts([row({}), row({ months_missing: ['2026-07'] }), row({ seal_due: '2026-09-30', months_missing: ['2026-07'] }), row({ next_seal_date: '2026-10-14' })], ctx)
    expect(counts).toMatchObject({ total: 4, onTrack: 1, atRisk: 2, overdue: 1, sealLate: 1, monthsLate: 2, tdsLate: 0, dueSoon: 1 })
  })
})

describe('standingContext', () => {
  it('matches a TDS deadline to a client by name only when the name is unique', () => {
    const clients = [row({ id: 'a', name: 'Alpha' }), row({ id: 'b', name: 'Twin' }), row({ id: 'c', name: 'Twin' })]
    const deadlines = [
      { date: '2026-10-15', label: 'TDS deposit', clients: ['Alpha', 'Twin'] },
      { date: '2026-10-16', label: 'Seal the books', clients: ['Alpha'] },
    ]
    const ctx = standingContext({ clients, deadlines } as never, TODAY)
    expect([...ctx.tdsDue!.entries()]).toEqual([['a', ['2026-10-15']]])
  })
})

describe('work waiting', () => {
  it('is entries only, and books in review are never added in', () => {
    const totals = { unresolved: 5, pending_approval: 3, ai_unchecked: 2, review_pending: 4 }
    expect(workWaiting(totals)).toBe(10)
    expect(booksInReview(totals)).toBe(4)
  })
})

describe('notes', () => {
  it('say every cause, and say plainly when there is none', () => {
    const none = { total: 3, onTrack: 3, atRisk: 0, overdue: 0, sealLate: 0, tdsLate: 0, monthsLate: 0, dueSoon: 0 }
    expect(lateNote(none)).toBe('No seal or TDS date has passed')
    expect(riskNote(none)).toBe('No date within 7 days, no month missing')
    expect(lateNote({ ...none, sealLate: 2, tdsLate: 1 })).toBe('2 past a seal date · 1 with TDS overdue')
    expect(riskNote({ ...none, dueSoon: 1, monthsLate: 2 })).toBe('1 with a date in 7 days · 2 with a month missing')
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
