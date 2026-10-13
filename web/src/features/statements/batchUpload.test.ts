import { describe, expect, it } from 'vitest'
import type { IngestResult, Job } from '@/api/types'
import { doneLine, isGapFailure, readingOrder, summariseBatch, type BatchItem, type Outcome } from './batchUpload'

const file = (name: string) => new File(['x'], name)
const done = (statement: string, over: Partial<IngestResult> = {}): Outcome => ({
  kind: 'done',
  statement: null,
  account: null,
  result: { statement, rows_created: 10, rows_need_ledger: 3, rows_ready_to_post: 5, ...over } as IngestResult,
})
const item = (name: string, outcome?: Outcome, state: BatchItem['state'] = 'finished'): BatchItem => ({ file: file(name), state, outcome })

describe('uploading several statements', () => {
  it('reads them in name order with numbers in order, so months named in sequence go in sequence', () => {
    const names = readingOrder([file('stmt 10.pdf'), file('stmt 2.pdf'), file('Stmt 1.pdf')]).map((f) => f.name)
    expect(names).toEqual(['Stmt 1.pdf', 'stmt 2.pdf', 'stmt 10.pdf'])
  })

  it('does not change the list it was given', () => {
    const given = [file('b.pdf'), file('a.pdf')]
    readingOrder(given)
    expect(given.map((f) => f.name)).toEqual(['b.pdf', 'a.pdf'])
  })

  it('tells a gap caused by the order of the files from other failures', () => {
    const gap: Outcome = { kind: 'failed', job: { error_code: 'statement_period_missing' } as Job }
    const other: Outcome = { kind: 'failed', job: { error_code: 'balance_chain_broken' } as Job }
    expect(isGapFailure(gap)).toBe(true)
    expect(isGapFailure(other)).toBe(false)
    expect(isGapFailure(undefined)).toBe(false)
    expect(isGapFailure(done('s1'))).toBe(false)
  })

  it('sums what was read, what needs a person, what failed and what is still waiting', () => {
    const sum = summariseBatch([
      item('a', done('s1')),
      item('b', done('s2', { rows_created: 4, rows_need_ledger: 0, rows_ready_to_post: 4 })),
      item('c', { kind: 'password', wrong: false }),
      item('d', { kind: 'failed', job: { error_code: 'balance_chain_broken' } as Job }),
      item('e', { kind: 'error', reason: 'Network' }),
      item('f', undefined, 'waiting'),
      item('g', undefined, 'reading'),
    ])
    expect(sum).toMatchObject({ total: 7, read: 2, needYou: 1, failed: 2, waiting: 2, rowsRead: 14, rowsToReview: 12, statementIds: ['s1', 's2'] })
  })

  it('says where a statement stands in a line', () => {
    expect(doneLine(done('s1') as Extract<Outcome, { kind: 'done' }>)).toBe('10 rows · 3 need a ledger · 5 ready to post')
    expect(doneLine(done('s1', { rows_created: 1, rows_need_ledger: 0, rows_ready_to_post: 1 }) as Extract<Outcome, { kind: 'done' }>)).toBe('1 row · 1 ready to post')
    expect(doneLine(done('s1', { rows_created: 0 }) as Extract<Outcome, { kind: 'done' }>)).toContain('Already on file')
  })
})
