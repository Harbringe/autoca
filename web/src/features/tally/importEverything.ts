// What the first Tally button does after the ledgers and bank accounts are made: bring in the rest of what was chosen. The ledger list's opening
// balances (when nothing in them needs a decision), then every vouchers file, posted. Each call is passed in, so the order and the stopping points
// are the whole of this module and it can be tested without a screen. Nothing here decides for the person what only they can decide: a preview
// that asks about the firm's own voucher types, a month with entries already in the books, or a ledger line that needs a choice is left where
// the cards below pick it up, and the summary says so.

import { ApiError } from '@/api/errors'
import type { MastersRun, VoucherRun, VoucherUpload } from '@/api/queries/tallyImport'
import type { Job } from '@/api/types'

export interface ChosenFile {
  file: File
  kind: 'vouchers' | 'ledgers' | 'bank_report' | 'ignored'
}

export interface ImportDeps {
  stageVouchers: (file: File) => Promise<VoucherUpload>
  isReadJob: (answer: VoucherUpload) => answer is Job
  waitForRead: (job: Job) => Promise<Job>
  confirmVouchers: (runId: string) => Promise<VoucherRun>
  /** Read the stored file again, with what the firm's own voucher types count as. */
  refreshVouchers: (runId: string, voucherTypes: Record<string, string>) => Promise<VoucherRun>
  postAll: () => Promise<{ queued: number }>
  stageMasters: (file: File, financialYear: number) => Promise<MastersRun>
  confirmMasters: (runId: string) => Promise<MastersRun>
  stageBankReports: (reports: { file: File; account: string }[]) => Promise<VoucherRun>
  bankAccounts: () => Promise<{ id: string; ledger_name?: string | null }[]>
  /** What is happening now, for the person watching. */
  say: (now: string) => void
  /** The year balances are as at when nothing in the files says. */
  defaultYear: number
}

const TYPE_LABEL: Record<string, string> = {
  sales: 'Sales',
  purchase: 'Purchase',
  'credit note': 'Credit note',
  'debit note': 'Debit note',
  journal: 'Journal',
  payment: 'Payment',
  receipt: 'Receipt',
  contra: 'Contra',
}

/** What a firm's own voucher type plainly is, from its name ("GST SALE" is sales, "Sales Return" a credit note); empty when the name does not say. */
export function guessVoucherType(name: string): string {
  const n = name.replace(/[^a-z0-9/ ]+/gi, ' ').replace(/\s+/g, ' ').trim().toLowerCase()
  if (/return/.test(n)) return /sale/.test(n) ? 'credit note' : /purchase|purc/.test(n) ? 'debit note' : ''
  if (/credit note|c\/note|cr note/.test(n)) return 'credit note'
  if (/debit note|d\/note|dr note/.test(n)) return 'debit note'
  if (/sale/.test(n)) return 'sales'
  if (/purchase|purc/.test(n)) return 'purchase'
  if (/journal|jrnl/.test(n)) return 'journal'
  if (/payment|pymt/.test(n)) return 'payment'
  if (/receipt|rcpt/.test(n)) return 'receipt'
  if (/contra/.test(n)) return 'contra'
  return ''
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`
const fyStart = (isoDate: string) => {
  const d = new Date(`${isoDate}T00:00:00`)
  return d.getMonth() >= 3 ? d.getFullYear() : d.getFullYear() - 1
}
const normal = (s: string) => s.replace(/\s+/g, ' ').trim().toLowerCase()
const says = (e: unknown) => (e instanceof Error && e.message ? e.message : 'Something went wrong.')

/** Runs everything after the ledgers exist. Returns one plain sentence for each thing done or left for the person. */
export async function importEverything(chosen: ChosenFile[], reports: { file: string; ledger: string }[], deps: ImportDeps): Promise<string[]> {
  const out: string[] = []
  const voucherFiles = chosen.filter((c) => c.kind === 'vouchers')
  const ledgerFiles = chosen.filter((c) => c.kind === 'ledgers')
  const bankFiles = chosen.filter((c) => c.kind === 'bank_report')

  // 1. Each vouchers file is read into a preview. A small one is ready at once; a large one is read by a worker, one import per month.
  const ready: { name: string; run: VoucherRun }[] = []
  let large = 0
  for (const { file } of voucherFiles) {
    deps.say(`Reading ${file.name}…`)
    try {
      const answer = await deps.stageVouchers(file)
      if (deps.isReadJob(answer)) {
        const done = await deps.waitForRead(answer)
        if (done.status !== 'SUCCEEDED') {
          out.push(`${file.name} could not be read: ${done.error || 'the reader stopped.'}`)
          continue
        }
        const months = ((done.result ?? {}) as { months?: number }).months ?? 0
        large += 1
        out.push(`${file.name} was read into ${plural(months, 'month')}.`)
      } else {
        ready.push({ name: file.name, run: answer })
      }
    } catch (e) {
      out.push(`${file.name} could not be read: ${says(e)}`)
    }
  }

  // 2. The ledger list's opening balances, as at the start of the year the vouchers begin in. Applied only when no line needs a decision.
  const starts = ready.map((r) => r.run.counts.date_from).filter(Boolean).sort()
  const year = starts[0] ? fyStart(starts[0]) : deps.defaultYear
  for (const { file } of ledgerFiles) {
    deps.say(`Reading the opening balances in ${file.name}…`)
    try {
      const run = await deps.stageMasters(file, year)
      if (run.counts.conflict + run.counts.needs_group + run.counts.bank_conflicts > 0) {
        out.push(
          `${file.name}: ${plural(run.counts.conflict + run.counts.needs_group + run.counts.bank_conflicts, 'ledger line')} need${run.counts.conflict + run.counts.needs_group + run.counts.bank_conflicts === 1 ? 's' : ''} your decision before opening balances can be brought in. Choose the ledgers file in step 1 below.`,
        )
        continue
      }
      if (run.counts.with_opening === 0) {
        out.push(`${file.name} has no opening balances to bring in.`)
        continue
      }
      await deps.confirmMasters(run.id)
      out.push(`Opening balances from ${file.name} were brought in as at 1 April ${year}.`)
    } catch (e) {
      out.push(`The opening balances in ${file.name} were not brought in: ${says(e)}`)
    }
  }

  // 3. Post the vouchers. What needs the person is left in the queue below, and said.
  for (const item of ready) {
    const { name } = item
    let run = item.run
    // A firm's own voucher type whose name says what it is ("GST SALE") is read as that, and the summary says so. Any the name does not settle waits for the person.
    const asked = Object.keys(run.counts.unknown_types ?? {})
    const guessed = Object.fromEntries(asked.map((t) => [t, guessVoucherType(t)]))
    if (asked.length > 0 && asked.every((t) => guessed[t])) {
      try {
        run = await deps.refreshVouchers(run.id, guessed)
        out.push(`${name}: ${asked.map((t) => `${t} was read as ${TYPE_LABEL[guessed[t]!]}`).join(', ')}.`)
      } catch (e) {
        out.push(`${name} could not be read again with those voucher types: ${says(e)}`)
        continue
      }
    }
    const unknown = Object.keys(run.counts.unknown_types ?? {})
    if (run.counts.will_post === 0) {
      out.push(`${name}: none of its ${plural(run.counts.vouchers, 'voucher')} could be posted (${run.counts.skipped} left out). Open it under Imports below to see why.`)
      continue
    }
    if (unknown.length > 0) {
      out.push(`${name}: it uses voucher types of the firm's own (${unknown.join(', ')}). Say what they count as under Imports below, then post it.`)
      continue
    }
    deps.say(`Posting ${name}…`)
    try {
      const done = await deps.confirmVouchers(run.id)
      const posted = done.result?.posted ?? run.counts.will_post
      out.push(
        `${name}: ${done.posting ? `${plural(run.counts.will_post, 'voucher')} are being posted` : `${plural(posted, 'voucher')} posted`}` +
          (run.counts.skipped ? `, ${run.counts.skipped} left out (the reasons are under Imports below).` : '.'),
      )
    } catch (e) {
      out.push(e instanceof ApiError && e.code === 'tally_overlap' ? `${name}: the books already hold entries for these months. Open it under Imports below and say whether to post.` : `${name} was not posted: ${says(e)}`)
    }
  }
  if (large > 0) {
    deps.say('Posting the months…')
    try {
      const { queued } = await deps.postAll()
      out.push(`${plural(queued, 'month')} queued to post, oldest first.`)
    } catch (e) {
      out.push(e instanceof ApiError && e.code === 'tally_overlap' ? 'Some months already have entries in the books, so none were posted. Open Imports below and say whether to post.' : `The months were not queued to post: ${says(e)}`)
    }
  }

  // 4. Bank reports carry the same bank entries as the vouchers do, so they are only brought in when there are no vouchers.
  if (bankFiles.length > 0) {
    if (voucherFiles.length > 0) {
      out.push(`The ${plural(bankFiles.length, 'bank report')} ${bankFiles.length === 1 ? 'was' : 'were'} not imported: the vouchers already carry those bank entries, and using both would count them twice.`)
    } else {
      deps.say('Reading the bank reports…')
      try {
        const accounts = await deps.bankAccounts()
        const picked: { file: File; account: string }[] = []
        for (const { file } of bankFiles) {
          const ledger = reports.find((r) => r.file === file.name)?.ledger ?? ''
          const account = accounts.find((a) => a.ledger_name && ledger && normal(a.ledger_name) === normal(ledger))
          if (account) picked.push({ file, account: account.id })
          else out.push(`${file.name}: no bank account of the client matches ${ledger ? `“${ledger}”` : 'it'}. Use the bank reports card below.`)
        }
        if (picked.length > 0) {
          const run = await deps.stageBankReports(picked)
          const done = await deps.confirmVouchers(run.id)
          out.push(`${plural(picked.length, 'bank report')}: ${done.posting ? 'being posted' : `${plural(done.result?.posted ?? run.counts.will_post, 'entry', 'entries')} posted`}.`)
        }
      } catch (e) {
        out.push(`The bank reports were not imported: ${says(e)}`)
      }
    }
  }
  return out
}
