import { describe, expect, it } from 'vitest'
import type { Classification } from '@/api/types'
import { reviewStage, waitingByStatement, waitingWords } from './statementReview'

const row = (statement: string) => ({ transaction: { statement } }) as unknown as Classification

describe('reviewing a statement from the statement', () => {
  const by = waitingByStatement([row('a'), row('a'), row('b')], [row('a'), row('c')])

  it('counts what is waiting in each statement, rows needing a ledger and rows ready to post apart', () => {
    expect(by.get('a')).toEqual({ needs: 2, ready: 1 })
    expect(by.get('b')).toEqual({ needs: 1, ready: 0 })
    expect(by.get('c')).toEqual({ needs: 0, ready: 1 })
    expect(by.get('d')).toBeUndefined()
  })

  it('says it in words, and says nothing for a statement that is all posted', () => {
    expect(waitingWords(by.get('a'))).toBe('2 need a ledger · 1 ready to post')
    expect(waitingWords(by.get('b'))).toBe('1 needs a ledger')
    expect(waitingWords(by.get('c'))).toBe('1 ready to post')
    expect(waitingWords(undefined)).toBeNull()
  })

  it('opens the rows needing a ledger first, else the ones ready to post', () => {
    expect(reviewStage(by.get('a'))).toBe('unresolved')
    expect(reviewStage(by.get('c'))).toBe('pending_approval')
    expect(reviewStage(undefined)).toBe('pending_approval')
  })
})
