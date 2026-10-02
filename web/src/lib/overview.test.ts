import type { OverviewClient } from '@/api/types'
import { booksWord, monthsText, needsAttention, nextTarget, STAGES, STAGE_LABEL } from './overview'

const c = (over: Partial<OverviewClient>): OverviewClient =>
  ({
    id: 'x',
    name: 'X',
    lead: null,
    stage: 'signed_off',
    next_step: { code: 'none', label: '', count: 0 },
    unresolved: 0,
    pending_approval: 0,
    assistant_waiting: 0,
    ai_unchecked: 0,
    review_pending: false,
    signed_off_through: null,
    last_statement_end: null,
    months_missing: [],
    ...over,
  }) as OverviewClient

describe('overview readings', () => {
  it('names every stage, in workflow order', () => {
    expect(STAGES).toHaveLength(6)
    STAGES.forEach((s) => expect(STAGE_LABEL[s]).toBeTruthy())
    expect(STAGES.indexOf('ready_for_review')).toBeLessThan(STAGES.indexOf('in_review'))
  })
  it('sends each next step to the screen where it is done', () => {
    expect(nextTarget('upload').to).toBe('/clients/$clientId/statements')
    expect(nextTarget('place')).toEqual({ to: '/clients/$clientId/review', search: { stage: 'unresolved' } })
    expect(nextTarget('post').search).toEqual({ stage: 'pending_approval' })
    expect(nextTarget('send_for_review').to).toBe('/clients/$clientId/books')
    expect(nextTarget('sign_off').to).toBe('/clients/$clientId/books')
    expect(nextTarget('none').to).toBe('/clients/$clientId')
  })
  it('says Sent for review only while a decision is pending', () => {
    expect(booksWord(c({ review_pending: true })).label).toBe('Sent for review')
    expect(booksWord(c({})).label).toBe('Working draft')
  })
  it('lists who needs a person: rows to place first, then ready to post, top N, none for quiet clients', () => {
    const list = needsAttention(
      [
        c({ id: 'a', name: 'A', pending_approval: 9 }),
        c({ id: 'b', name: 'B', unresolved: 2 }),
        c({ id: 'q', name: 'Quiet' }),
        c({ id: 'd', name: 'D', unresolved: 2, pending_approval: 5 }),
      ],
      2,
    )
    expect(list.map((x) => x.id)).toEqual(['d', 'b'])
    expect(needsAttention([c({ id: 'q' })])).toEqual([])
  })
  it('writes months', () => expect(monthsText(['2026-04', '2026-06'])).toBe('Apr 2026, Jun 2026'))
})
