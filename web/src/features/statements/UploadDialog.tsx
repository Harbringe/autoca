// Uploading a bank statement, from anywhere in a client's workspace.
//
// The one question a new user asks -- "where do I put the statement?" -- is answered by a
// button on every tab that opens this. It says what file to bring, reads it, and then says
// what happened in the terms that matter: which period, how many rows, how many the rules
// and the assistant already dealt with, and what is left to do. If the account is new it
// asks for the opening balance there and then, because every balance after depends on it.

import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { CheckCircle2, FileUp, Loader2, UploadCloud, XCircle } from 'lucide-react'
import { createContext, useCallback, useContext, useEffect, useRef, useState, type DragEvent, type ReactNode } from 'react'
import { raw } from '@/api/client'
import { isApiError, messageOf } from '@/api/errors'
import { UPLOAD_PROBLEMS, waitForJob } from '@/api/jobs'
import { clientDetail, useInvalidateClient, V1 } from '@/api/queries/clients'
import type { BankAccount, IngestResult, Job, Statement } from '@/api/types'
import { Button } from '@/components/ui/button'
import { DateInput } from '@/components/ui/date-input'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { formatDate, formatPaise, parseDate, parseRupees, plural } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'

const MAX_BYTES = 25 * 1024 * 1024

interface UploadApi {
  open: () => void
}
const Ctx = createContext<UploadApi | null>(null)

export function useUpload(): UploadApi {
  const value = useContext(Ctx)
  if (!value) throw new Error('useUpload outside UploadProvider')
  return value
}

export function UploadProvider({ clientId, children }: { clientId: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const openIt = useCallback(() => setOpen(true), [])
  useEffect(() => {
    const listener = () => setOpen(true)
    document.addEventListener('autoca:upload', listener)
    return () => document.removeEventListener('autoca:upload', listener)
  }, [])
  return (
    <Ctx.Provider value={{ open: openIt }}>
      {children}
      {open && <UploadDialog clientId={clientId} onClose={() => setOpen(false)} />}
    </Ctx.Provider>
  )
}

type Phase =
  | { kind: 'choose'; file: File | null; problem?: string }
  | { kind: 'reading'; file: File; job?: Job }
  | { kind: 'done'; file: File; result: IngestResult; statement: Statement | null; account: BankAccount | null }
  | { kind: 'failed'; file: File; job: Job }

function UploadDialog({ clientId, onClose }: { clientId: string; onClose: () => void }) {
  const [phase, setPhase] = useState<Phase>({ kind: 'choose', file: null })
  const invalidate = useInvalidateClient(clientId)
  const client = useQuery(clientDetail(clientId))

  async function send(file: File, allowGap = false) {
    setPhase({ kind: 'reading', file })
    try {
      const form = new FormData()
      form.append('file', file)
      if (allowGap) form.append('allow_gap', 'true')
      const created = await raw.post<Job>(`${V1}/clients/${clientId}/statements/upload/`, form)
      setPhase({ kind: 'reading', file, job: created })
      const job = await waitForJob(created, (update) => setPhase({ kind: 'reading', file, job: update }))
      if (job.status === 'FAILED') {
        setPhase({ kind: 'failed', file, job })
        return
      }
      const result = job.result as IngestResult
      const [statement, account] = await Promise.all([
        raw.get<Statement>(`${V1}/clients/${clientId}/statements/${result.statement}/`).catch(() => null),
        raw.get<BankAccount>(`${V1}/clients/${clientId}/bank-accounts/${result.bank_account}/`).catch(() => null),
      ])
      setPhase({ kind: 'done', file, result, statement, account })
      await invalidate()
    } catch (error) {
      const reason = isApiError(error) ? (error.field('file') ?? error.message) : messageOf(error)
      setPhase({ kind: 'choose', file: null, problem: reason })
    }
  }

  const reading = phase.kind === 'reading'
  return (
    <Dialog open onOpenChange={(next) => !next && !reading && onClose()}>
      <DialogContent className="max-w-xl" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Upload bank statement</DialogTitle>
          <DialogDescription>{client.data?.name}</DialogDescription>
        </DialogHeader>
        {phase.kind === 'choose' && <Chooser phase={phase} setPhase={setPhase} onSend={(f) => void send(f)} />}
        {phase.kind === 'reading' && <Reading file={phase.file} job={phase.job} />}
        {phase.kind === 'failed' && (
          <Failed
            job={phase.job}
            onRetry={() => setPhase({ kind: 'choose', file: null })}
            onAllowGap={() => void send(phase.file, true)}
          />
        )}
        {phase.kind === 'done' && (
          <Done clientId={clientId} phase={phase} onClose={onClose} onAnother={() => setPhase({ kind: 'choose', file: null })} />
        )}
      </DialogContent>
    </Dialog>
  )
}

function Chooser({
  phase,
  setPhase,
  onSend,
}: {
  phase: Extract<Phase, { kind: 'choose' }>
  setPhase: (p: Phase) => void
  onSend: (file: File) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)

  function take(file: File | undefined) {
    if (!file) return
    if (!/\.pdf$/i.test(file.name) && file.type !== 'application/pdf')
      return setPhase({ kind: 'choose', file: null, problem: 'That is not a PDF. Upload the statement as a PDF file.' })
    if (file.size > MAX_BYTES)
      return setPhase({ kind: 'choose', file: null, problem: 'That file is over 25 MB. Download one month or quarter at a time.' })
    if (file.size === 0) return setPhase({ kind: 'choose', file: null, problem: 'That file is empty.' })
    setPhase({ kind: 'choose', file })
  }

  function drop(event: DragEvent) {
    event.preventDefault()
    setOver(false)
    take(event.dataTransfer.files[0])
  }

  return (
    <div className="grid gap-4">
      <button
        type="button"
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
        className={cn(
          'grid justify-items-center gap-2 rounded-lg border-2 border-dashed p-8 text-center transition-colors hover:bg-hover',
          over && 'border-primary bg-hover',
        )}
      >
        <UploadCloud className="size-8 text-muted-foreground" aria-hidden />
        {phase.file ? (
          <>
            <span className="font-medium">{phase.file.name}</span>
            <span className="text-xs text-muted-foreground">{(phase.file.size / 1024).toFixed(0)} KB · click to choose a different file</span>
          </>
        ) : (
          <>
            <span className="font-medium">Drop the statement PDF here, or click to choose</span>
            <span className="text-xs text-muted-foreground">One file at a time</span>
          </>
        )}
      </button>
      <input ref={input} type="file" accept="application/pdf,.pdf" className="hidden" onChange={(e) => take(e.target.files?.[0])} />

      <div className="rounded-md bg-muted/60 p-3 text-[13px] text-muted-foreground">
        <div className="mb-1 font-medium text-foreground">What to upload</div>
        <ul className="list-disc space-y-0.5 pl-5">
          <li>The client’s <strong>bank account statement</strong>, downloaded as a PDF from net banking. Any bank.</li>
          <li>A text PDF, not a scan or a photo. If you can select the text in it, it will work.</li>
          <li>Up to 25 MB. Upload months in order; a gap between statements is flagged.</li>
          <li>The account is recognised from the statement, so a new account is set up for you.</li>
        </ul>
      </div>

      {phase.problem && (
        <p role="alert" className="text-sm text-destructive">
          {phase.problem}
        </p>
      )}

      <div className="flex justify-end">
        <Button onClick={() => phase.file && onSend(phase.file)} disabled={!phase.file}>
          <FileUp /> Upload and read
        </Button>
      </div>
    </div>
  )
}

function Reading({ file, job }: { file: File; job?: Job }) {
  // The bar is the server's own progress figure (0 to 100). Until the server has answered there is
  // no figure to show, so the bar says nothing rather than pretending.
  const progress = job ? Math.min(100, Math.max(0, job.progress)) : null
  return (
    <div className="grid gap-3 py-6" role="status">
      <div className="flex items-center gap-2 font-medium">
        <Loader2 className="size-4 shrink-0 animate-spin motion-reduce:animate-none" aria-hidden />
        <span className="min-w-0 truncate">{job?.message || `Sending ${file.name}`}</span>
      </div>
      <div
        role="progressbar"
        aria-label={`Reading ${file.name}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress ?? undefined}
        className="h-2 overflow-hidden rounded-full bg-muted"
      >
        <div className="h-full rounded-full bg-primary" style={{ width: `${progress ?? 0}%` }} />
      </div>
      <p className="text-[13px] text-muted-foreground">
        {progress === null ? 'Sending the file.' : `${progress}%`} Every row is checked against the running balance, then the client’s rules
        place what they can. The assistant reads the rest after this, a few rows at a time. A long statement can take up to a minute.
      </p>
    </div>
  )
}

function Failed({ job, onRetry, onAllowGap }: { job: Job; onRetry: () => void; onAllowGap: () => void }) {
  const problem = UPLOAD_PROBLEMS[job.error_code] ?? { title: 'The statement was not imported', help: '' }
  return (
    <div className="grid gap-4">
      <div className="flex gap-3 rounded-md border border-destructive/40 bg-destructive-bg p-4">
        <XCircle className="mt-0.5 size-5 shrink-0 text-destructive" aria-hidden />
        <div className="grid gap-1.5 text-sm">
          <div className="font-semibold">{problem.title}</div>
          {problem.help && <p>{problem.help}</p>}
          {job.error && <p className="text-muted-foreground">{job.error}</p>}
          <p className="text-muted-foreground">Nothing was imported.</p>
        </div>
      </div>
      <div className="flex justify-end gap-2">
        {job.error_code === 'statement_period_missing' && (
          <Button variant="outline" onClick={onAllowGap}>
            Import anyway, leaving the gap
          </Button>
        )}
        <Button onClick={onRetry}>Choose another file</Button>
      </div>
    </div>
  )
}

function Done({
  clientId,
  phase,
  onClose,
  onAnother,
}: {
  clientId: string
  phase: Extract<Phase, { kind: 'done' }>
  onClose: () => void
  onAnother: () => void
}) {
  const navigate = useNavigate()
  const { result, statement, account } = phase
  const nothingNew = result.rows_created === 0
  // The server says where the statement's rows stand; older servers only sent the step tallies.
  const posted = result.rows_posted ?? result.auto_posted
  const needLedger = result.rows_need_ledger ?? 0
  const ready = result.rows_ready_to_post ?? Math.max(0, result.rows_created - posted - needLedger)
  const leftForYou = ready + needLedger
  const waitingForAssistant = Math.min(result.waiting_for_assistant ?? 0, needLedger)
  const [openingDone, setOpeningDone] = useState(!result.needs_opening_confirmation)

  const facts: [string, string | number][] = [
    ['Bank account', account?.label ?? '—'],
    ['Period', statement ? `${formatDate(statement.period_start)} to ${formatDate(statement.period_end)}` : '—'],
    ['Rows read', result.rows_created],
  ]
  if (result.rows_already_present) facts.push(['Already on file (skipped)', result.rows_already_present])
  if (statement) {
    facts.push(['Opening balance', statement.opening_balance_display ?? '—'])
    facts.push(['Closing balance', statement.closing_balance_display ?? '—'])
  }

  return (
    <div className="grid gap-4">
      <div className="flex gap-3 rounded-md border border-success/30 bg-success-bg p-4">
        <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-success" aria-hidden />
        <div className="text-sm">
          <div className="font-semibold">
            {nothingNew ? 'Already imported' : `Imported ${plural(result.rows_created, 'transaction')}`}
          </div>
          <p className="text-muted-foreground">
            {nothingNew
              ? 'Every row in this file was already on file, so nothing changed.'
              : 'Every row was checked against the statement’s running balance, and the totals agree.'}
          </p>
        </div>
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
        {facts.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="num text-right font-medium">{v}</dd>
          </div>
        ))}
      </dl>

      {!nothingNew && (
        <div className="rounded-md bg-muted/60 p-3 text-sm">
          <div className="mb-1 font-medium">
            {plural(result.rows_created, 'row')} read. {posted} posted by rules, {ready} ready to post, {needLedger} need a ledger.
          </div>
          <ul className="grid gap-0.5 text-muted-foreground">
            {posted > 0 && (
              <li>
                <strong className="text-foreground">{posted}</strong> posted already, where a rule was very sure. They are marked “Assistant
                posted” in the Day Book: check them there, and unpost any you disagree with.
              </li>
            )}
            <li>
              <strong className="text-foreground">{ready}</strong> placed in a ledger and waiting for you to check and post
            </li>
            <li>
              <strong className="text-foreground">{needLedger}</strong> need a ledger
              {waitingForAssistant > 0 && (
                <>
                  , <strong className="text-foreground">{waitingForAssistant}</strong> of them waiting for the assistant, which reads them a few at a
                  time while this client is open. They appear in Review as it goes.
                </>
              )}
            </li>
          </ul>
        </div>
      )}

      {!openingDone && account && (
        <OpeningBalance clientId={clientId} account={account} statement={statement} onDone={() => setOpeningDone(true)} />
      )}

      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="ghost" onClick={onAnother}>
          Upload another
        </Button>
        <Button variant="outline" onClick={onClose}>
          Close
        </Button>
        {leftForYou > 0 && (
          <Button
            onClick={() => {
              onClose()
              void navigate({ to: '/clients/$clientId/review', params: { clientId }, search: { stage: needLedger ? 'unresolved' : 'pending_approval' } })
            }}
          >
            Review {leftForYou} {leftForYou === 1 ? 'row' : 'rows'}
          </Button>
        )}
      </div>
    </div>
  )
}

/** The balance the account held before the first row on file. Reconciliation is meaningless without it. */
export function OpeningBalance({
  clientId,
  account,
  statement,
  onDone,
  compact,
}: {
  clientId: string
  account: BankAccount
  statement?: Statement | null
  onDone: () => void
  compact?: boolean
}) {
  const { can } = useSession()
  const invalidate = useInvalidateClient(clientId)
  const [amount, setAmount] = useState(
    account.opening_balance_paise != null
      ? String(account.opening_balance_paise / 100)
      : statement?.opening_balance_paise != null
        ? String(statement.opening_balance_paise / 100)
        : '',
  )
  const [asOf, setAsOf] = useState(formatDate(account.opening_as_of ?? statement?.period_start ?? ''))
  const [error, setError] = useState<string | null>(null)
  // The server refuses a figure that contradicts the statement beginning on that date; the person may keep it on purpose.
  const [differs, setDiffers] = useState(false)
  const [busy, setBusy] = useState(false)

  if (!can('ledger.manage')) {
    return <p className="text-sm text-warning">The opening balance for {account.label} is not confirmed yet. Ask a colleague who manages ledgers.</p>
  }

  async function save(acknowledge = false) {
    const paise = parseRupees(amount)
    const date = parseDate(asOf)
    if (paise === null) return setError('Enter the amount in rupees, for example 1,25,000.00.')
    if (!date) return setError('Enter the date as DD-MM-YYYY.')
    setBusy(true)
    setError(null)
    setDiffers(false)
    try {
      await raw.post(`${V1}/clients/${clientId}/bank-accounts/${account.id}/opening-balance/`, {
        opening_balance_paise: paise,
        opening_as_of: date,
        acknowledge_difference: acknowledge,
      })
      await invalidate()
      onDone()
    } catch (e) {
      setDiffers(isApiError(e) && e.code === 'opening_differs')
      setError(messageOf(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={cn('grid gap-3', !compact && 'rounded-md border border-accent-edge bg-accent p-4')}>
      {!compact && (
        <div className="text-sm">
          <div className="font-semibold">Confirm the opening balance of {account.label}</div>
          <p className="text-muted-foreground">
            The balance on the first day, before any row on this statement. It is filled in from the statement; check it against the
            client’s previous books.
          </p>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        <Field label="Opening balance (₹)">
          {(p) => <Input {...p} inputMode="decimal" className="text-right num" value={amount} onChange={(e) => setAmount(e.target.value)} />}
        </Field>
        <Field label="As at">{(p) => <DateInput {...p} value={asOf} onChange={(e) => setAsOf(e.target.value)} />}</Field>
      </div>
      {statement?.opening_balance_paise != null && (
        <p className="text-xs text-muted-foreground">
          The statement opens at {formatPaise(statement.opening_balance_paise)}
          {statement.opening_balance_paise < 0 ? ' (negative: an overdrawn account)' : ''}. A negative figure here means overdrawn too.
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex justify-end gap-2">
        {differs && (
          <Button size="sm" variant="outline" onClick={() => void save(true)} disabled={busy}>
            Keep my figure anyway
          </Button>
        )}
        <Button size="sm" onClick={() => void save()} disabled={busy}>
          {busy ? 'Saving…' : 'Confirm opening balance'}
        </Button>
      </div>
    </div>
  )
}
