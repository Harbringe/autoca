import { describe, expect, it } from 'vitest'
import { leadSentence } from './overviewLead'

describe('leadSentence', () => {
  it('names the work in the order it is done', () => {
    expect(leadSentence({ unresolved: 6, pending: 6, invoices: 0, fixes: 0 })).toBe('12 items need you: sort 6, then record 6.')
    expect(leadSentence({ unresolved: 31, pending: 40, invoices: 2, fixes: 4 })).toBe('77 items need you: sort 31, then record 40, then book 2 invoices, then tie out 4 items.')
  })
  it('skips what is not waiting and keeps singular grammar', () => {
    expect(leadSentence({ unresolved: 0, pending: 0, invoices: 1, fixes: 0 })).toBe('1 item needs you: book 1 invoice.')
  })
  it('says so when nothing is waiting', () => {
    expect(leadSentence({ unresolved: 0, pending: 0, invoices: 0, fixes: 0 })).toBe('Nothing is waiting on this client.')
    expect(leadSentence({ unresolved: 6, pending: 6, invoices: 0, fixes: 0, assistant: 6 })).toBe('12 items need you: sort 6, then record 6. The assistant is working on 6 rows now.')
  })
})
