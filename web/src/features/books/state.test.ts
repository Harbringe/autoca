import { booksState, lockLabel } from './state'

const event = (action: string) => ({ action }) as never

describe('booksState', () => {
  it('is awaiting the senior while a request is open', () => {
    expect(booksState({ review_pending: true, history: [event('REQUESTED')] })).toBe('awaiting_senior')
  })
  it('is returned when the last word was a return', () => {
    expect(booksState({ review_pending: false, history: [event('RETURNED'), event('REQUESTED')] })).toBe('returned')
  })
  it('goes back to draft once a sign-off or reopen follows', () => {
    expect(booksState({ review_pending: false, history: [event('SIGNED_OFF'), event('RETURNED')] })).toBe('draft')
    expect(booksState({ review_pending: false, history: [event('REOPENED')] })).toBe('draft')
    expect(booksState({ review_pending: false, history: [] })).toBe('draft')
  })
})

describe('lockLabel', () => {
  it('names the date the books are locked through', () => {
    expect(lockLabel({ signed_off_through: '2026-03-31' })).toBe('Signed off through 31-03-2026')
    expect(lockLabel({ signed_off_through: null })).toBeNull()
  })
})
