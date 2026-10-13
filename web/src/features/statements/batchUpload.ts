// Uploading several bank statements at once: the order they are read in, and what the batch says about itself. Free of React so it can be tested.

import type { BankAccount, IngestResult, Job, Statement } from '@/api/types'

/** What reading one file came to. */
export type Outcome =
  | { kind: 'done'; result: IngestResult; statement: Statement | null; account: BankAccount | null }
  | { kind: 'password'; wrong: boolean }
  | { kind: 'failed'; job: Job }
  | { kind: 'error'; reason: string }

export interface BatchItem {
  file: File
  state: 'waiting' | 'reading' | 'finished'
  outcome?: Outcome
}

/** The files in the order they are read: by name, with numbers in order (Jan2, Jan10), so months named in sequence go in sequence. */
export function readingOrder(files: readonly File[]): File[] {
  return [...files].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }))
}

/** A statement for a gap the files themselves caused: read before its neighbour. Worth one more try once the others are in. */
export const isGapFailure = (o: Outcome | undefined): boolean => o?.kind === 'failed' && o.job.error_code === 'statement_period_missing'

export interface BatchSummary {
  total: number
  read: number
  needYou: number
  failed: number
  waiting: number
  rowsRead: number
  /** Rows left to place or post across the statements that were read. */
  rowsToReview: number
  /** The statements that were read, for a link that opens Review on exactly them. */
  statementIds: string[]
}

export function summariseBatch(items: readonly BatchItem[]): BatchSummary {
  const s: BatchSummary = { total: items.length, read: 0, needYou: 0, failed: 0, waiting: 0, rowsRead: 0, rowsToReview: 0, statementIds: [] }
  for (const item of items) {
    const o = item.outcome
    if (item.state !== 'finished' || !o) s.waiting += 1
    else if (o.kind === 'done') {
      s.read += 1
      s.rowsRead += o.result.rows_created
      s.rowsToReview += (o.result.rows_need_ledger ?? 0) + (o.result.rows_ready_to_post ?? 0)
      s.statementIds.push(o.result.statement)
    } else if (o.kind === 'password') s.needYou += 1
    else s.failed += 1
  }
  return s
}

/** One line for a statement that was read: where it stands. */
export function doneLine(o: Extract<Outcome, { kind: 'done' }>): string {
  const rows = `${o.result.rows_created} ${o.result.rows_created === 1 ? 'row' : 'rows'}`
  const need = o.result.rows_need_ledger ?? 0
  const ready = o.result.rows_ready_to_post ?? 0
  if (o.result.rows_created === 0) return 'Already on file: nothing new in it'
  return [rows, need ? `${need} need a ledger` : '', ready ? `${ready} ready to post` : ''].filter(Boolean).join(' · ')
}
