import { describe, expect, it } from 'vitest'
import { waitingNote } from './jobs'
import type { Job } from './types'

const now = new Date('2026-10-20T12:00:00Z').getTime()

function job(over: Partial<Job>): Job {
  return {
    id: 'j',
    kind: 'statement.ingest',
    status: 'PENDING',
    progress: 0,
    message: '',
    result: {},
    error: '',
    error_code: '',
    created_at: '2026-10-20T11:59:30Z',
    started_at: null,
    finished_at: null,
    queue_ahead: 0,
    reader_running: true,
    ...over,
  } as Job
}

describe('waitingNote', () => {
  it('says nothing about a job that is not waiting', () => {
    expect(waitingNote(job({ status: 'RUNNING' }), now)).toBeNull()
    expect(waitingNote(job({ status: 'SUCCEEDED' }), now)).toBeNull()
    expect(waitingNote(undefined, now)).toBeNull()
  })

  it('says how many are ahead, as a count and never a time', () => {
    expect(waitingNote(job({ queue_ahead: 1 }), now)).toBe('Waiting its turn: 1 file is ahead of this one.')
    expect(waitingNote(job({ queue_ahead: 3 }), now)).toBe('Waiting its turn: 3 files are ahead of this one.')
    expect(waitingNote(job({ queue_ahead: 0 }), now)).toBe('Waiting to be read.')
  })

  it('does not call the reader down on a pending job alone, or before two minutes have passed', () => {
    expect(waitingNote(job({ reader_running: true, created_at: '2026-10-20T11:50:00Z' }), now)).toBe('Waiting to be read.')
    expect(waitingNote(job({ reader_running: false, created_at: '2026-10-20T11:59:00Z' }), now)).toBe('Waiting to be read.')
  })

  it('says the reader is not running only when it has not polled and the job has waited over two minutes', () => {
    expect(waitingNote(job({ reader_running: false, created_at: '2026-10-20T11:57:00Z' }), now)).toContain('not running')
  })
})
