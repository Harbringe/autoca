import type { Alert } from '@/api/types'
import { actionLabel, adviceFor } from './alertAdvice'

const alert = (over: Partial<Alert>) => ({ kind: 'review', title: '', to: '/clients/c1/review', search: {}, ...over }) as Alert

describe('what to do about an alert', () => {
  it('tells the two jobs of one kind apart by the screen they open', () => {
    expect(adviceFor(alert({ kind: 'review', search: { stage: 'unresolved' } }))).toMatch(/Place each in a ledger/)
    expect(adviceFor(alert({ kind: 'review', search: { stage: 'pending_approval' } }))).toMatch(/post them/)
  })
  it('tells a seal that is ready from one that is overdue', () => {
    expect(adviceFor(alert({ kind: 'seal', title: 'Approved and ready to seal' }))).toMatch(/Seal the books/)
    expect(adviceFor(alert({ kind: 'seal', title: 'Books are due to be sealed' }))).toMatch(/Finish the checklist/)
  })
  it('has a line for every kind the server sends, and a fallback for one it does not know', () => {
    for (const kind of ['statements', 'unchecked', 'review_pending', 'bank', 'control', 'approval', 'tds', 'tds_due']) {
      expect(adviceFor(alert({ kind }))).not.toMatch(/follow what the screen shows/)
    }
    expect(adviceFor(alert({ kind: 'something_new' }))).toMatch(/follow what the screen shows/)
  })
  it('names the screen it opens', () => {
    expect(actionLabel(alert({ to: '/clients/c1/review' }))).toBe('Open Review')
    expect(actionLabel(alert({ to: '/clients/c1/tds' }))).toBe('Open TDS')
    expect(actionLabel(alert({ to: '/clients/c1/books' }))).toBe('Open Sign-off')
    expect(actionLabel(alert({ to: '/clients/c1/daybook' }))).toBe('Open Day Book')
  })
})
