// Uploading a bank statement, from anywhere in a client's workspace.
//
// The one question a new user asks -- "where do I put the statement?" -- is answered by a
// button on every tab that opens this. It says what file to bring, reads it, and then says
// what happened in the terms that matter: which period, how many rows, how many the rules
// and the assistant already dealt with, and what is left to do. If the account is new it
// asks for the opening balance there and then, because every balance after depends on it.

import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { CheckCircle2, CircleAlert, Clock, FileUp, Loader2, UploadCloud, XCircle } from 'lucide-react'
import { GrowFill } from '@/components/charts/ProgressBar'
import { createContext, useCallback, useContext, useEffect, useRef, useState, type DragEvent, type ReactNode } from 'react'
import { raw } from '@/api/client'
import { isApiError, messageOf } from '@/api/errors'
import { UPLOAD_PROBLEMS, waitForJob } from '@/api/jobs'
import { clientDetail, useInvalidateClient, V1 } from '@/api/queries/clients'
import type { BankAccount, IngestResult, Job, Statement } from '@/api/types'
import { isLockedCode, PasswordForm } from '@/components/ca/PasswordPrompt'
import { Button } from '@/components/ui/button'
import { DateInput } from '@/components/ui/date-input'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { LayoutPicker } from './LayoutPicker'
import { doneLine, isGapFailure, readingOrder, summariseBatch, type BatchItem, type Outcome } from './batchUpload'
import { formatDate, formatPaise, parseDate, parseRupees, plural } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { ACCEPT, ACCEPTED_NAME } from '@/lib/fileTypes'

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
  | { kind: 'layout'; file: File; job: Job }
  | { kind: 'password'; file: File; wrong: boolean }
  | { kind: 'batch'; items: BatchItem[]; running: boolean }

/** Sends one file and says how it came out. Used for a single upload and, one after another, for a batch. */
async function uploadOne(
  clientId: string,
  file: File,
  options: { allowGap?: boolean; layout?: Record<string, number>; password?: string; onJob?: (job: Job) => void } = {},
): Promise<Outcome> {
  try {
    const form = new FormData()
    form.append('file', file)
    if (options.allowGap) form.append('allow_gap', 'true')
    if (options.layout) form.append('layout', JSON.stringify(options.layout))
    if (options.password) form.append('password', options.password)
    const created = await raw.post<Job>(`${V1}/clients/${clientId}/statements/upload/`, form)
    options.onJob?.(created)
    const job = await waitForJob(created, (update) => options.onJob?.(update))
    if (job.status === 'FAILED') {
      // A locked PDF is asked for its password; anything else is a failure to read.
      if (isLockedCode(job.error_code)) return { kind: 'password', wrong: job.error_code === 'password_incorrect' }
      return { kind: 'failed', job }
    }
    const result = job.result as IngestResult
    const [statement, account] = await Promise.all([
      raw.get<Statement>(`${V1}/clients/${clientId}/statements/${result.statement}/`).catch(() => null),
      raw.get<BankAccount>(`${V1}/clients/${clientId}/bank-accounts/${result.bank_account}/`).catch(() => null),
    ])
    return { kind: 'done', result, statement, account }
  } catch (error) {
    return { kind: 'error', reason: isApiError(error) ? (error.field('file') ?? error.message) : messageOf(error) }
  }
}

function UploadDialog({ clientId, onClose }: { clientId: string; onClose: () => void }) {
  const [phase, setPhase] = useState<Phase>({ kind: 'choose', file: null })
  const invalidate = useInvalidateClient(clientId)
  const client = useQuery(clientDetail(clientId))

  async function send(file: File, allowGap = false, layout?: Record<string, number>, password?: string) {
    setPhase({ kind: 'reading', file })
    const outcome = await uploadOne(clientId, file, { allowGap, layout, password, onJob: (job) => setPhase({ kind: 'reading', file, job }) })
    if (outcome.kind === 'password') setPhase({ kind: 'password', file, wrong: outcome.wrong })
    else if (outcome.kind === 'failed') setPhase({ kind: 'failed', file, job: outcome.job })
    else if (outcome.kind === 'error') setPhase({ kind: 'choose', file: null, problem: outcome.reason })
    else {
      setPhase({ kind: 'done', file, result: outcome.result, statement: outcome.statement, account: outcome.account })
      await invalidate()
    }
  }

  /** Several files: read one after another (a statement is checked against the one before it, so they cannot run side by side). */
  async function sendMany(chosen: File[]) {
    let items: BatchItem[] = readingOrder(chosen).map((file) => ({ file, state: 'waiting' }))
    const show = (running: boolean) => setPhase({ kind: 'batch', items: [...items], running })
    const set = (index: number, change: Partial<BatchItem>) => {
      items = items.map((item, i) => (i === index ? { ...item, ...change } : item))
      show(true)
    }
    show(true)
    const readAt = async (index: number) => {
      set(index, { state: 'reading' })
      const outcome = await uploadOne(clientId, items[index]!.file)
      set(index, { state: 'finished', outcome })
    }
    for (let i = 0; i < items.length; i++) await readAt(i)
    // A statement that was read before its neighbour is flagged as a gap; with the others in, it may now fit.
    for (let i = 0; i < items.length; i++) if (isGapFailure(items[i]!.outcome)) await readAt(i)
    show(false)
    await invalidate()
  }

  /** One file of a batch that needs a person: carry on with it alone, in the same steps as a single upload. */
  function openAlone(item: BatchItem) {
    const o = item.outcome
    if (o?.kind === 'password') setPhase({ kind: 'password', file: item.file, wrong: o.wrong })
    else if (o?.kind === 'failed') setPhase({ kind: 'failed', file: item.file, job: o.job })
  }

  const busy = phase.kind === 'reading' || (phase.kind === 'batch' && phase.running)
  return (
    <Dialog open onOpenChange={(next) => !next && !busy && onClose()}>
      <DialogContent className="max-w-xl" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Upload bank statements</DialogTitle>
          <DialogDescription>{client.data?.name}</DialogDescription>
        </DialogHeader>
        {phase.kind === 'choose' && <Chooser phase={phase} setPhase={setPhase} onSend={(f) => void send(f)} onSendMany={(files) => void sendMany(files)} />}
        {phase.kind === 'batch' && (
          <Batch clientId={clientId} phase={phase} onOpenAlone={openAlone} onClose={onClose} onMore={() => setPhase({ kind: 'choose', file: null })} />
        )}
        {phase.kind === 'reading' && <Reading file={phase.file} job={phase.job} />}
        {phase.kind === 'password' && (
          <PasswordForm
            fileName={phase.file.name}
            wrong={phase.wrong}
            onSubmit={(password) => void send(phase.file, false, undefined, password)}
            onCancel={() => setPhase({ kind: 'choose', file: null })}
          />
        )}
        {phase.kind === 'failed' && (
          <Failed
            job={phase.job}
            onRetry={() => setPhase({ kind: 'choose', file: null })}
            onAllowGap={() => void send(phase.file, true)}
            onLayout={() => setPhase({ kind: 'layout', file: phase.file, job: phase.job })}
          />
        )}
        {phase.kind === 'layout' && (
          <LayoutPicker
            clientId={clientId}
            file={phase.file}
            onTry={(layout) => void send(phase.file, false, layout)}
            onBack={() => setPhase({ kind: 'failed', file: phase.file, job: phase.job })}
          />
        )}
        {phase.kind === 'done' && (
          <Done clientId={clientId} phase={phase} onClose={onClose} onAnother={() => setPhase({ kind: 'choose', file: null })} />
        )}
      </DialogContent>
    </Dialog>
  )
}

/** Why a file cannot be read, or null when it can. */
function problemWith(file: File): string | null {
  if (!ACCEPTED_NAME.test(file.name)) return 'That kind of file cannot be read. Upload a PDF, an Excel sheet (.xlsx), a CSV, a Word file (.docx) or a photo of the statement (JPG, PNG).'
  if (file.size > MAX_BYTES) return 'That file is over 25 MB. Download one month or quarter at a time.'
  if (file.size === 0) return 'That file is empty.'
  return null
}

function Chooser({
  phase,
  setPhase,
  onSend,
  onSendMany,
}: {
  phase: Extract<Phase, { kind: 'choose' }>
  setPhase: (p: Phase) => void
  onSend: (file: File) => void
  onSendMany: (files: File[]) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  // Several files chosen at once. One file is the ordinary single upload, with all its steps.
  const [many, setMany] = useState<File[]>([])

  function take(list: FileList | File[] | null | undefined) {
    const files = Array.from(list ?? [])
    if (files.length === 0) return
    const usable = files.filter((f) => !problemWith(f))
    const skipped = files.length - usable.length
    if (usable.length === 0) {
      setMany([])
      return setPhase({ kind: 'choose', file: null, problem: problemWith(files[0]!) ?? undefined })
    }
    const note = skipped ? `${skipped} ${skipped === 1 ? 'file was' : 'files were'} left out: ${problemWith(files.find((f) => problemWith(f))!)}` : undefined
    if (usable.length === 1) {
      setMany([])
      return setPhase({ kind: 'choose', file: usable[0]!, problem: note })
    }
    setMany(usable)
    setPhase({ kind: 'choose', file: null, problem: note })
  }

  function drop(event: DragEvent) {
    event.preventDefault()
    setOver(false)
    take(event.dataTransfer.files)
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
        {many.length > 1 ? (
          <>
            <span className="font-medium">{many.length} statements chosen</span>
            <span className="max-w-full truncate text-xs text-muted-foreground">{many.slice(0, 3).map((f) => f.name).join(', ')}{many.length > 3 ? ` and ${many.length - 3} more` : ''}</span>
            <span className="text-xs text-muted-foreground">Click to choose different files</span>
          </>
        ) : phase.file ? (
          <>
            <span className="font-medium">{phase.file.name}</span>
            <span className="text-xs text-muted-foreground">{(phase.file.size / 1024).toFixed(0)} KB · click to choose different files</span>
          </>
        ) : (
          <>
            <span className="font-medium">Drop the statements here, or click to choose</span>
            <span className="text-xs text-muted-foreground">One or several files at once</span>
          </>
        )}
      </button>
      <input ref={input} type="file" multiple accept={ACCEPT} className="hidden" aria-label="Choose statements" onChange={(e) => take(e.target.files)} />

      <div className="rounded-md bg-muted/60 p-3 text-[13px] text-muted-foreground">
        <div className="mb-1 font-medium text-foreground">What to upload</div>
        <ul className="list-disc space-y-0.5 pl-5">
          <li>The client’s <strong>bank account statement</strong>, as downloaded from net banking: a PDF, an Excel sheet (.xlsx), a CSV or a Word file. Any bank.</li>
          <li>A photo or scan (JPG, PNG, TIFF) is read by the assistant when that is switched on. A downloaded file is always more reliable than a photo.</li>
          <li>Up to 25 MB each. Choose several at once and they are read one after another; a statement with a gap before it is tried again once the rest are in, and one that needs you (a password, say) is left for you to open.</li>
          <li>The account is recognised from the statement, so a new account is set up for you.</li>
        </ul>
      </div>

      {phase.problem && (
        <p role="alert" className="text-sm text-destructive">
          {phase.problem}
        </p>
      )}

      <div className="flex justify-end">
        <Button onClick={() => (many.length > 1 ? onSendMany(many) : phase.file && onSend(phase.file))} disabled={!phase.file && many.length < 2}>
          <FileUp /> {many.length > 1 ? `Upload and read ${many.length} statements` : 'Upload and read'}
        </Button>
      </div>
    </div>
  )
}

function BatchRow({ clientId, item, onOpenAlone }: { clientId: string; item: BatchItem; onOpenAlone: (item: BatchItem) => void }) {
  const o = item.outcome
  const [confirming, setConfirming] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const openingToConfirm = o?.kind === 'done' && o.result.needs_opening_confirmation && !confirmed && !!o.account
  let icon = <Clock className="size-4 text-muted-foreground" aria-hidden />
  let line = 'Waiting'
  let tone = 'text-muted-foreground'
  if (item.state === 'reading') {
    icon = <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
    line = 'Reading…'
    tone = ''
  } else if (o?.kind === 'done') {
    icon = <CheckCircle2 className="size-4 text-success" aria-hidden />
    const period = o.statement ? `${formatDate(o.statement.period_start)} to ${formatDate(o.statement.period_end)}` : ''
    line = [o.account?.label, period, doneLine(o)].filter(Boolean).join(' · ')
    tone = ''
  } else if (o?.kind === 'password') {
    icon = <CircleAlert className="size-4 text-warning" aria-hidden />
    line = o.wrong ? 'The password did not open it' : 'Password-protected: needs its password'
    tone = ''
  } else if (o?.kind === 'failed') {
    icon = <XCircle className="size-4 text-destructive" aria-hidden />
    line = `${(UPLOAD_PROBLEMS[o.job.error_code] ?? { title: 'Not imported' }).title}. Nothing was imported.`
    tone = ''
  } else if (o?.kind === 'error') {
    icon = <XCircle className="size-4 text-destructive" aria-hidden />
    line = o.reason
    tone = ''
  }
  return (
    <li className="grid gap-2 px-4 py-3 text-sm">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 shrink-0">{icon}</span>
        <span className="min-w-0 flex-1">
          <b className="block truncate font-medium text-heading">{item.file.name}</b>
          <span className={cn('block [overflow-wrap:anywhere]', tone)}>{line}</span>
        </span>
        {(o?.kind === 'password' || o?.kind === 'failed') && (
          <Button size="sm" variant="outline" className="shrink-0" onClick={() => onOpenAlone(item)}>
            Open on its own
          </Button>
        )}
        {openingToConfirm && (
          <Button size="sm" variant="outline" className="shrink-0" onClick={() => setConfirming((c) => !c)}>
            Confirm opening balance
          </Button>
        )}
      </div>
      {confirming && o?.kind === 'done' && o.account && (
        <OpeningBalance
          clientId={clientId}
          account={o.account}
          statement={o.statement}
          onDone={() => {
            setConfirmed(true)
            setConfirming(false)
          }}
        />
      )}
    </li>
  )
}

/** Several statements read one after another: each file's own line, then what to do next. */
function Batch({
  clientId,
  phase,
  onOpenAlone,
  onClose,
  onMore,
}: {
  clientId: string
  phase: Extract<Phase, { kind: 'batch' }>
  onOpenAlone: (item: BatchItem) => void
  onClose: () => void
  onMore: () => void
}) {
  const navigate = useNavigate()
  const sum = summariseBatch(phase.items)
  const attention = sum.needYou + sum.failed
  return (
    <div className="grid gap-4">
      <p role="status" className="text-sm">
        {phase.running ? (
          <>
            Reading <b>{sum.read + sum.needYou + sum.failed + 1 > sum.total ? sum.total : sum.read + sum.needYou + sum.failed + 1}</b> of {sum.total}. Every row is checked against the running balance.
          </>
        ) : (
          <>
            <b>{sum.read}</b> of {sum.total} read, {plural(sum.rowsRead, 'row')} in all
            {attention > 0 ? `; ${attention} ${attention === 1 ? 'needs' : 'need'} you.` : '.'}
          </>
        )}
      </p>
      <ul className="max-h-[50vh] divide-y overflow-y-auto overscroll-contain rounded-lg border">
        {phase.items.map((item, i) => (
          <BatchRow key={`${item.file.name}-${i}`} clientId={clientId} item={item} onOpenAlone={onOpenAlone} />
        ))}
      </ul>
      {!phase.running && (
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={onMore}>
            Upload more
          </Button>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
          {sum.rowsToReview > 0 && (
            <Button
              onClick={() => {
                onClose()
                void navigate({
                  to: '/clients/$clientId/review',
                  params: { clientId },
                  // Review opens on exactly the statements just read, so the counts and the rows are theirs.
                  search: { statement: sum.statementIds.join(',') },
                })
              }}
            >
              Review {plural(sum.rowsToReview, 'row')}
            </Button>
          )}
        </div>
      )}
    </div>
  )
}

function Reading({ file, job }: { file: File; job?: Job }) {
  // The bar is the server's own progress figure (0 to 100), but the server only reports 0 and then 100 (the whole read happens in
  // one step), so while there is no real figure a moving bar says "working" without claiming a percentage.
  const progress = job && job.progress > 0 ? Math.min(100, job.progress) : null
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
        {progress === null ? (
          <span className="block h-full w-2/5 animate-[slide-across_1.4s_ease-in-out_infinite] rounded-full bg-primary motion-reduce:animate-none" />
        ) : (
          <GrowFill id="upload-progress" percent={progress} className="rounded-full bg-primary" />
        )}
      </div>
      <p className="text-[13px] text-muted-foreground">
        {progress === null ? 'Sending the file.' : `${progress}%`} Every row is checked against the running balance, then the client’s rules
        place what they can. The assistant reads the rest after this, a few rows at a time. A long statement can take up to a minute.
      </p>
    </div>
  )
}

/** Failures that are about which column is which, where naming the columns can help. */
const LAYOUT_CODES = new Set(['statement_unreadable', 'columns_not_inferred', 'balance_chain_broken'])

function Failed({
  job,
  onRetry,
  onAllowGap,
  onLayout,
}: {
  job: Job
  onRetry: () => void
  onAllowGap: () => void
  onLayout: () => void
}) {
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
        {LAYOUT_CODES.has(job.error_code) && (
          <Button variant="outline" onClick={onLayout}>
            Show me how it was read
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
  const openingWorkedBack = !!result.opening_inferred && !!statement

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

      {openingWorkedBack && (
        <p role="status" className="rounded-md border border-accent-edge bg-accent px-3 py-2 text-sm text-accent-foreground">
          The statement printed <b>0.00</b> as its opening balance, but its first row needs <b>{statement?.opening_balance_display}</b>. That is the opening shown
          here, worked back from the first row; every row after it agrees with the balances the statement prints. Check it against the client’s books before you
          confirm it.
        </p>
      )}

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
      <div className="grid grid-cols-[3fr_2fr] gap-4 max-sm:grid-cols-1">
        <Field label="Opening balance (₹)">
          {(p) => <Input {...p} inputMode="decimal" className="h-12 rounded-lg text-right font-mono text-lg" value={amount} onChange={(e) => setAmount(e.target.value)} />}
        </Field>
        <Field label="As at">{(p) => <DateInput {...p} className="h-12 rounded-lg text-base" value={asOf} onChange={(e) => setAsOf(e.target.value)} />}</Field>
      </div>
      {statement?.opening_balance_paise != null && (
        <p className="text-sm text-muted-foreground">
          The statement opens at <span className="font-mono text-heading">{formatPaise(statement.opening_balance_paise)}</span>
          {statement.opening_balance_paise < 0 ? ' (negative: an overdrawn account)' : ''}. A negative figure here means overdrawn too.
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex flex-wrap justify-end gap-3 pt-1">
        {differs && (
          <Button size="lg" variant="outline" onClick={() => void save(true)} loading={busy}>
            Keep my figure anyway
          </Button>
        )}
        <Button size="lg" className="rounded-lg px-6 font-semibold" onClick={() => void save()} loading={busy}>
          {busy ? 'Saving…' : 'Confirm opening balance'}
        </Button>
      </div>
    </div>
  )
}
