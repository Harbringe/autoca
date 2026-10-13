// Books & sign-off: the maker-checker step, and the lock that follows it.
//
// One sentence says where the books are and what is left; one checklist holds everything that must clear, each line
// opening to its own way of clearing it; then the step that follows: send for review, approve or return, seal.
// The preparer sends the books to the senior CA once nothing is waiting. The senior either returns them with a note
// or approves them, and seals them on the client's schedule; from then on entries up to that date are locked and
// voucher numbers are final. Reopening is rare, needs a reason, and is recorded like everything else.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { CheckCircle2, Lock, RotateCcw, Send, Undo2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from '@/lib/toast'
import { raw } from '@/api/client'
import { journal } from '@/api/queries/books'
import { closeReport } from '@/api/queries/bills'
import { booksStatus, clientDetail, useInvalidateClient, V1 } from '@/api/queries/clients'
import type { BooksStatus } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { SegmentedMeter } from '@/components/charts/ProgressBar'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, formatDateTime, plural } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { ClosePanel } from './ClosePanel'
import { SealSchedule } from './SealSchedule'
import { SignOffChecklist } from './SignOffChecklist'
import { SignOffDialog } from './SignOffDialog'
import { signOffHeadline } from './signOffChecks'
import { BOOKS_STATE_HINT, BOOKS_STATE_LABEL, BOOKS_STATE_TONE, booksState } from './state'

type Action = 'request' | 'return' | 'approve' | 'sign-off' | 'reopen' | 'mark-reviewed' | null

export function BooksScreen({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const books = useQuery(booksStatus(clientId))
  const report = useQuery(closeReport(clientId))
  const entries = useQuery({ ...journal(clientId), enabled: can('journal.view') })
  const invalidate = useInvalidateClient(clientId)
  const [action, setAction] = useState<Action>(null)

  if (books.isPending) return <Spinner />
  if (books.error) return <ErrorState error={books.error} retry={() => void books.refetch()} />
  const b = books.data
  const state = booksState(b)
  const mayAct = can('books.request')
  const senior = can('books.sign_off') && b.can_sign_off
  const unchecked = b.ai_posted + b.ai_revised
  const canMark = mayAct && can('journal.correct') && !!client.data?.can_post && unchecked > 0
  const failing = report.data ? report.data.checks.filter((c) => !c.ok) : []
  const toClear = failing.length + (report.data?.unexplained_blocking ?? 0)
  const waitingEntries = (entries.data ?? []).filter((e) => e.marker)

  async function send(path: string, body: object, message: string) {
    await raw.post<BooksStatus>(`${V1}/clients/${clientId}/books/${path}/`, body)
    await invalidate()
    toast.success(message)
  }

  // The server takes up to 500 at a time and says how many it really marked; an entry someone else just changed is skipped.
  async function markMany(ids: string[]) {
    let marked = 0
    for (let i = 0; i < ids.length; i += 500) {
      const answer = await raw.post<{ marked?: number }>(`${V1}/clients/${clientId}/books/mark-reviewed/`, { entries: ids.slice(i, i + 500) })
      marked += answer?.marked ?? 0
    }
    await invalidate()
    if (marked === ids.length) toast.success(`${plural(marked, 'entry', 'entries')} marked as checked`)
    else toast.warning(`${marked} of ${ids.length} marked as checked`, { description: 'The rest had already changed: checked, unposted or sealed by someone else.' })
  }

  const headline = signOffHeadline({
    state,
    toClear,
    known: !!report.data,
    leadName: client.data?.lead?.name,
    nextSealDate: b.next_seal_date ? formatDate(b.next_seal_date) : null,
  })
  const checks = report.data?.checks ?? []
  const meterTotal = checks.length
  const passing = checks.filter((c) => c.ok).length

  return (
    <div>
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] [&>*]:min-w-0">
      <div className="grid gap-4 [&>*]:min-w-0">
      <Card className="grid gap-3 p-5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={BOOKS_STATE_TONE[state]}>{BOOKS_STATE_LABEL[state]}</Badge>
          {b.signed_off_through && (
            <Badge tone="info" icon={<Lock aria-hidden />}>
              Sealed through {formatDate(b.signed_off_through)}
            </Badge>
          )}
          {b.approved_through && state === 'approved' && <Badge tone="done">Approved through {formatDate(b.approved_through)}</Badge>}
          <span className="text-sm text-muted-foreground">{BOOKS_STATE_HINT[state]}</span>
        </div>
        <h2 className="text-xl font-semibold leading-snug text-heading">{headline}</h2>
        {meterTotal > 0 && (state === 'draft' || state === 'returned') && (
          <div className="flex items-center gap-3">
            <SegmentedMeter id={`signoff-${clientId}`} total={meterTotal} done={passing} label={`${passing} of ${meterTotal} checks passing`} className="flex-1" />
            <span className="num shrink-0 text-sm text-muted-foreground">
              {passing} of {meterTotal} clear
            </span>
          </div>
        )}

        {state === 'approved' && (
          <div className="rounded-md border p-3 text-sm" role="status">
            <div className="font-medium">
              Approved by {b.approved_by || 'the senior'}
              {b.approved_at ? ` on ${formatDateTime(b.approved_at)}` : ''}, through {b.approved_through ? formatDate(b.approved_through) : ''}.
            </div>
            <p className="text-muted-foreground">
              Nothing is locked yet. Entries can still be changed; any change inside that period is counted here and the approval has to be
              given again before sealing.
            </p>
            {b.changed_since_approval > 0 && (
              <p className="mt-1 font-medium text-destructive">
                {plural(b.changed_since_approval, 'entry', 'entries')} changed since the approval. Approve again before sealing.
              </p>
            )}
          </div>
        )}
        {state === 'returned' && b.returned_note && (
          <div className="rounded-md border border-destructive/40 bg-destructive-bg p-3 text-sm">
            <div className="font-medium">Returned by {b.history.find((h) => h.action === 'RETURNED')?.actor_email ?? 'the reviewer'}</div>
            <p>{b.returned_note}</p>
          </div>
        )}
        {b.review_pending && (
          <p className="text-sm text-muted-foreground">
            Sent for review by {b.requested_by}
            {b.requested_at ? ` on ${formatDateTime(b.requested_at)}` : ''}. Changes made now are still included when it is approved.
          </p>
        )}
      </Card>

      {report.isPending ? (
        <Spinner label="Checking what is open…" />
      ) : report.isError ? (
        <ErrorState error={report.error} retry={() => void report.refetch()} />
      ) : (
        <SignOffChecklist
          clientId={clientId}
          checks={report.data.checks}
          entries={waitingEntries}
          canMark={canMark}
          onMark={markMany}
          onMarkAll={() => setAction('mark-reviewed')}
        />
      )}

      <ClosePanel clientId={clientId} maySignOff={senior} />
      </div>

      <div className="grid gap-4 [&>*]:min-w-0">
      <Card className="grid gap-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-heading">{b.review_pending || state === 'approved' ? 'Review and seal' : 'Send for review'}</h2>
            <p className="text-sm text-muted-foreground">
              {mayAct && !b.review_pending && !b.can_request && b.waiting > 0 ? (
                <>
                  Can be sent once nothing is waiting.{' '}
                  <Link to="/clients/$clientId/review" params={{ clientId }} search={{ stage: 'all' }} className="underline">
                    {plural(b.waiting, 'transaction')} in Review
                  </Link>
                  .
                </>
              ) : !senior && b.review_pending ? (
                <>Waiting for {client.data?.lead?.name ?? 'a firm administrator (no senior CA is assigned)'} to approve or return it.</>
              ) : mayAct && !b.review_pending && b.can_request ? (
                'Everything the server checks for sending is in order.'
              ) : (
                ' '
              )}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {mayAct && !b.review_pending && (
              <Button onClick={() => setAction('request')} disabled={!b.can_request}>
                <Send /> Send for review
              </Button>
            )}
            {senior && (b.review_pending || (state === 'approved' && b.changed_since_approval > 0)) && (
              <Button onClick={() => setAction('approve')} title={unchecked > 0 ? 'Assistant entries must be checked first' : undefined}>
                <CheckCircle2 /> {b.review_pending ? 'Approve the books' : 'Approve again'}
              </Button>
            )}
            {senior && b.review_pending && (
              <Button variant="outline" onClick={() => setAction('return')}>
                <Undo2 /> Return with a note
              </Button>
            )}
            {senior && b.sealable_dates.length > 0 && (
              <Button variant="outline" onClick={() => setAction('sign-off')}>
                <Lock /> Seal the books
              </Button>
            )}
            {senior && b.signed_off_through && (
              <Button variant="outline" onClick={() => setAction('reopen')}>
                <RotateCcw /> Reopen
              </Button>
            )}
          </div>
        </div>

        <ol className="grid gap-2 text-sm sm:grid-cols-3" aria-label="What happens next">
          <Step done={state === 'awaiting_senior' || state === 'approved'} n={1} title="You send it" hint={state === 'draft' || state === 'returned' ? 'When every check passes' : 'Sent'} />
          <Step done={state === 'approved'} n={2} title="The senior approves" hint={state === 'approved' ? 'Approved' : 'Reviews and signs off'} />
          <Step done={!!b.signed_off_through && state !== 'approved'} n={3} title="The books are sealed" hint={b.next_seal_date ? `On ${formatDate(b.next_seal_date)}, locked for good` : 'On the schedule, locked for good'} />
        </ol>
      </Card>

      <SealSchedule clientId={clientId} books={b} mayChange={senior && can('client.update')} />

      <details className="group rounded-lg border bg-card">
        <summary className="flex min-h-11 cursor-pointer items-center px-5 text-sm font-medium text-heading">History ({b.history.length})</summary>
        <div className="px-5 pb-4">
          {b.history.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nothing yet. The books have never been sent for review.</p>
          ) : (
            <ol className="grid gap-3 border-l pl-4 text-sm">
              {b.history.map((h) => (
                <li key={h.id} className="relative">
                  <span className="absolute -left-[21px] top-1.5 size-2.5 rounded-full bg-primary" aria-hidden />
                  <div className="font-medium">
                    {h.action_display}
                    {h.through_date && ` through ${formatDate(h.through_date)}`}
                  </div>
                  <div className="text-muted-foreground">
                    {h.actor_email ?? '—'} · {formatDateTime(h.created_at)}
                  </div>
                  {h.note && <p className="mt-0.5">“{h.note}”</p>}
                </li>
              ))}
            </ol>
          )}
        </div>
      </details>
      </div>
      </div>

      <Confirm
        open={action === 'request'}
        onOpenChange={(o) => !o && setAction(null)}
        title="Send the books for review?"
        confirmLabel="Send for review"
        note="optional"
        noteLabel="Note for the senior CA (optional)"
        onConfirm={(note) => send('request', { note }, 'Sent to the senior CA')}
      >
        <p>
          {client.data?.lead
            ? `${client.data.lead.name}, the client’s senior CA, will`
            : 'This client has no senior CA assigned, so a firm administrator will'}{' '}
          check the books and either sign them off or return them.
        </p>
      </Confirm>
      <Confirm
        open={action === 'return'}
        onOpenChange={(o) => !o && setAction(null)}
        title="Return the books?"
        confirmLabel="Return with note"
        note="required"
        noteLabel="What needs to change (required)"
        onConfirm={(note) => send('return', { note }, 'Returned to the preparer')}
      >
        <p>The preparer sees your note and sends them again when done.</p>
      </Confirm>
      <SignOffDialog clientId={clientId} books={b} open={action === 'sign-off'} onOpenChange={(o) => !o && setAction(null)} />
      <Confirm
        open={action === 'approve'}
        onOpenChange={(o) => !o && setAction(null)}
        title="Approve the books?"
        confirmLabel="Approve"
        note="optional"
        noteLabel="Note (optional)"
        onConfirm={(note) => send('approve', { note }, 'Books approved')}
      >
        <p>
          This says the books are good, through the latest entry. It locks nothing: entries stay editable, and a change made afterwards is
          reported so you can approve again. The books are sealed later, on the client’s schedule.
        </p>
      </Confirm>
      <Confirm
        open={action === 'reopen'}
        onOpenChange={(o) => !o && setAction(null)}
        title="Reopen signed-off books?"
        confirmLabel="Reopen"
        destructive
        note="required"
        noteLabel="Why they are being reopened (required, kept on record)"
        onConfirm={(note) => send('reopen', { note }, 'Books reopened')}
      >
        <p>
          This undoes the latest sign-off only; the lock goes back to where it was before it. If there were several sign-offs, reopen again to
          go further back.
        </p>
      </Confirm>
      <Confirm
        open={action === 'mark-reviewed'}
        onOpenChange={(o) => !o && setAction(null)}
        title={`Mark ${plural(unchecked, 'assistant entry', 'assistant entries')} as checked?`}
        confirmLabel="Mark as checked"
        onConfirm={() => send('mark-reviewed', {}, 'Assistant entries marked as checked')}
      >
        <p>Only do this once you have looked at them in the Day Book (filter “Assistant entries only”). The marker is removed from each.</p>
      </Confirm>
    </div>
  )
}

/** One step of what happens after the books are sent: you send, the senior approves, the books are sealed. */
function Step({ n, title, hint, done }: { n: number; title: string; hint: string; done: boolean }) {
  return (
    <li className="flex items-start gap-3">
      <span
        aria-hidden
        className={cn('grid size-6 shrink-0 place-items-center rounded-full border text-xs font-semibold', done ? 'border-success bg-success text-primary-foreground' : 'border-input text-muted-foreground')}
      >
        {done ? '✓' : n}
      </span>
      <span>
        <span className={cn('block font-medium', done ? 'text-heading' : 'text-foreground')}>{title}</span>
        <span className="block text-xs text-muted-foreground">
          {done && <span className="sr-only">Done. </span>}
          {hint}
        </span>
      </span>
    </li>
  )
}
