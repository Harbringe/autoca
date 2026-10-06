import { booksState, latestEntryDate, lockLabel, signOffPreview } from './state'

const event = (action: string) => ({ action }) as never

describe('booksState', () => {
  it('is awaiting the senior while a request is open', () => {
    expect(booksState({ review_pending: true, history: [event('REQUESTED')] })).toBe('awaiting_senior')
  })
  it('is returned when the last word was a return', () => {
    expect(booksState({ review_pending: false, history: [event('RETURNED'), event('REQUESTED')] })).toBe('returned')
  })
  it('is approved, not sealed, after the senior approves', () => {
    const approved = { review_pending: false, history: [event('APPROVED')], approved_through: '2026-06-30', signed_off_through: null }
    expect(booksState(approved)).toBe('approved')
    expect(booksState({ ...approved, signed_off_through: '2026-06-30' })).toBe('draft')
  })
  it('goes back to draft once a sign-off or reopen follows', () => {
    expect(booksState({ review_pending: false, history: [event('SIGNED_OFF'), event('RETURNED')] })).toBe('draft')
    expect(booksState({ review_pending: false, history: [event('REOPENED')] })).toBe('draft')
    expect(booksState({ review_pending: false, history: [] })).toBe('draft')
  })
})

describe('lockLabel', () => {
  it('names the date the books are locked through', () => {
    expect(lockLabel({ signed_off_through: '2026-03-31' })).toBe('Sealed through 31-03-2026')
    expect(lockLabel({ signed_off_through: null })).toBeNull()
  })
})

describe('signOffPreview', () => {
  const e = (entry_date: string, amount: number, marker = '') => ({
    entry_date,
    marker,
    lines: [
      { direction: 'DR' as const, amount_paise: amount },
      { direction: 'CR' as const, amount_paise: amount },
    ],
  })
  const entries = [e('2026-04-10', 100), e('2026-05-02', 250, 'AI_POSTED'), e('2026-06-01', 400, 'AI_REVISED')]
  it('counts vouchers and totals up to the date, and unchecked assistant entries', () => {
    expect(signOffPreview(entries, '2026-05-31', null)).toEqual({ vouchers: 2, drPaise: 350, crPaise: 350, unchecked: 1 })
  })
  it('leaves out what an earlier sign-off already locked', () => {
    expect(signOffPreview(entries, '2026-06-30', '2026-04-30')).toMatchObject({ vouchers: 2, drPaise: 650, unchecked: 2 })
  })
  it('finds the latest entry date', () => {
    expect(latestEntryDate(entries)).toBe('2026-06-01')
    expect(latestEntryDate([])).toBeNull()
  })
})
