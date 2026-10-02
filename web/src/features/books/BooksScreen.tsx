// Books & sign-off: the maker-checker step, and the lock that follows it.
//
// The preparer sends the books to the senior CA once nothing is waiting. The senior either
// returns them with a note or signs them off through a date; from then on entries up to that
// date are locked and voucher numbers are final. Reopening is rare, needs a reason, and is
// recorded like everything else. Every step, by whom and when, is listed below.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { CheckCircle2, Lock, RotateCcw, Send, Undo2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { booksStatus, clientDetail, useInvalidateClient, V1 } from '@/api/queries/clients'
import type { BooksStatus } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { StatCard } from '@/components/ui/stat-card'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, formatDateTime, plural } from '@/lib/format'
import { useSession } from '@/session/session'
import { SignOffDialog } from './SignOffDialog'
import { BOOKS_STATE_HINT, BOOKS_STATE_LABEL, BOOKS_STATE_TONE, booksState } from './state'

type Action = 'request' | 'return' | 'sign-off' | 'reopen' | 'mark-reviewed' | null

export function BooksScreen({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const books = useQuery(booksStatus(clientId))
  const invalidate = useInvalidateClient(clientId)
  const [action, setAction] = useState<Action>(null)

  if (books.isPending) return <Spinner />
  if (books.error) return <ErrorState error={books.error} retry={() => void books.refetch()} />
  const b = books.data
  const state = booksState(b)
  const mayAct = can('books.request')
  const senior = can('books.sign_off') && b.can_sign_off
  const unchecked = b.ai_posted + b.ai_revised

  async function send(path: string, body: object, message: string) {
    await raw.post<BooksStatus>(`${V1}/clients/${clientId}/books/${path}/`, body)
    await invalidate()
    toast.success(message)
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
      <div className="grid content-start gap-4">
        <Card className="grid gap-4 p-5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={BOOKS_STATE_TONE[state]}>{BOOKS_STATE_LABEL[state]}</Badge>
            {b.signed_off_through && (
              <Badge tone="info" icon={<Lock aria-hidden />}>
                Signed off through {formatDate(b.signed_off_through)}
              </Badge>
            )}
            <span className="text-sm text-muted-foreground">{BOOKS_STATE_HINT[state]}</span>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <StatCard label="Waiting for a decision or posting" value={b.waiting} to="/clients/$clientId/review" params={{ clientId }} search={{ stage: 'all' }} />
            <StatCard label="Assistant entries not yet checked" value={b.ai_posted} tone={b.ai_posted > 0 ? 'attention' : 'plain'} to="/clients/$clientId/daybook" params={{ clientId }} />
            <StatCard label="Changed by the assistant after a correction" value={b.ai_revised} tone={b.ai_revised > 0 ? 'attention' : 'plain'} to="/clients/$clientId/daybook" params={{ clientId }} />
          </div>

          {unchecked > 0 && (
            <div className="rounded-md border border-accent-edge bg-accent p-3 text-sm" role="status">
              <div className="font-medium">
                {plural(unchecked, 'entry', 'entries')} posted by the assistant, not yet checked
              </div>
              <p className="text-muted-foreground">
                Next step: look at {unchecked === 1 ? 'it' : 'them'} in the Day Book, then mark {unchecked === 1 ? 'it' : 'them'} as checked. The books
                cannot be signed off until then.
              </p>
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
              {b.requested_at ? ` on ${formatDateTime(b.requested_at)}` : ''}. Changes made now are still included when it is signed off.
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            {mayAct && !b.review_pending && (
              <Button onClick={() => setAction('request')} disabled={!b.can_request}>
                <Send /> Send for review
              </Button>
            )}
            {senior && b.review_pending && (
              <>
                <Button onClick={() => setAction('sign-off')} title={unchecked > 0 ? 'Assistant entries must be checked first' : undefined}>
                  <CheckCircle2 /> Sign off the books
                </Button>
                <Button variant="outline" onClick={() => setAction('return')}>
                  <Undo2 /> Return with a note
                </Button>
              </>
            )}
            {senior && b.signed_off_through && (
              <Button variant="outline" onClick={() => setAction('reopen')}>
                <RotateCcw /> Reopen
              </Button>
            )}
            {mayAct && can('journal.correct') && client.data?.can_post && unchecked > 0 && (
              <>
                <Button variant="ghost" onClick={() => setAction('mark-reviewed')}>
                  Mark assistant entries as checked
                </Button>
                <Button asChild variant="ghost">
                  <Link to="/clients/$clientId/daybook" params={{ clientId }}>
                    Review or unpost them in the Day Book
                  </Link>
                </Button>
              </>
            )}
          </div>
          {mayAct && !b.review_pending && !b.can_request && b.waiting > 0 && (
            <p className="text-sm text-muted-foreground">
              Can be sent once nothing is waiting.{' '}
              <Link to="/clients/$clientId/review" params={{ clientId }} search={{ stage: 'all' }} className="underline">
                {plural(b.waiting, 'transaction')} in Review
              </Link>
              .
            </p>
          )}
          {!senior && b.review_pending && (
            <p className="text-sm text-muted-foreground">
              Waiting for {client.data?.lead?.name ?? 'a firm administrator (no senior CA is assigned)'} to sign off or return it.
            </p>
          )}
        </Card>

        <Card className="grid gap-2 p-5 text-sm">
          <div className="font-medium">Export to Tally</div>
          <p className="text-muted-foreground">
            Each statement’s posted vouchers export as a Tally XML file from the{' '}
            <Link to="/clients/$clientId/statements" params={{ clientId }} className="underline">
              Statements
            </Link>{' '}
            tab. Import it in Tally under Gateway of Tally › Import › Vouchers. Importing the same file again updates the vouchers; it does not
            duplicate them. Ledger names must match the client’s Tally company exactly.
          </p>
        </Card>
      </div>

      <Card className="content-start p-5">
        <div className="mb-2 font-medium">History</div>
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
      </Card>

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
        title={`Mark ${plural(b.ai_posted + b.ai_revised, 'assistant entry', 'assistant entries')} as checked?`}
        confirmLabel="Mark as checked"
        onConfirm={() => send('mark-reviewed', {}, 'Assistant entries marked as checked')}
      >
        <p>Only do this once you have looked at them in the Day Book (filter “Assistant entries only”). The marker is removed from each.</p>
      </Confirm>
    </div>
  )
}
