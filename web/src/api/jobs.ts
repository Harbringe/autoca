import { raw } from './client'
import type { Job } from './types'

/**
 * Follow a job until it finishes. Work runs inline on the server today, so the job is
 * normally finished already; this keeps working unchanged when it moves to a worker.
 * Polling, not a stream, so it works the same in a browser and in a desktop shell.
 */
export async function waitForJob(job: Job, onUpdate?: (job: Job) => void): Promise<Job> {
  let current = job
  let delay = 500
  while (current.status === 'PENDING' || current.status === 'RUNNING') {
    await new Promise((resolve) => setTimeout(resolve, delay))
    current = await raw.get<Job>(`/api/v1/jobs/${current.id}/`)
    onUpdate?.(current)
    delay = Math.min(delay * 1.5, 3000)
  }
  return current
}

/** What went wrong with an upload, in the words a CA needs, keyed by the job's error code. */
export const UPLOAD_PROBLEMS: Record<string, { title: string; help: string }> = {
  no_text_layer: {
    title: 'This PDF is a scan, not a text statement',
    help: 'Download the statement again from net banking as a PDF (not a scan, photo or printout) and upload that file.',
  },
  unsupported_bank: {
    title: 'The statement’s layout was not recognised',
    help: 'Check this is a bank account statement (not a credit card or loan statement). If it is, download it again from net banking in PDF format.',
  },
  columns_not_inferred: {
    title: 'The columns could not be worked out',
    help: 'The date, amount and balance columns were not clear enough to read safely. Try the PDF download from net banking rather than a converted file.',
  },
  balance_chain_broken: {
    title: 'The running balance does not add up',
    help: 'Nothing was imported. The message says which row broke the chain; usually a page is missing or the file was edited.',
  },
  statement_period_missing: {
    title: 'A period is missing before this statement',
    help: 'The last statement on file for this account ends before this one starts. Upload the missing months first, or import this one anyway if the gap is intended.',
  },
  statement_elsewhere: {
    title: 'This file belongs to another client',
    help: 'The same file is already on file for a different client of the firm. Check the client named at the top of this page, and the file.',
  },
  pages_missing: {
    title: 'Pages seem to be missing',
    help: 'The file looks cut off. Download the full statement again and retry.',
  },
  unreadable_file: {
    title: 'The file could not be read',
    help: 'It may be damaged, password-protected or not really a PDF. Download it again from the bank and retry.',
  },
  statement_unreadable: {
    title: 'The statement could not be read',
    help: 'Download it again from net banking as a PDF and retry.',
  },
}
