// Sign-off, said properly: what gets locked (the date, the vouchers and their totals), and what
// stands in the way. The server refuses while assistant-posted entries up to the date are unchecked,
// so the dialog shows the same count, disables the button with the reason, and offers the two ways out.

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { journal } from '@/api/queries/books'
import { clientDetail, clientKeys, useInvalidateClient, V1 } from '@/api/queries/clients'
import type { BooksStatus } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { Button } from '@/components/ui/button'
import { DateInput } from '@/components/ui/date-input'
import { Field } from '@/components/ui/field'
import { formatDate, formatPaise, parseDate, plural } from '@/lib/format'
import { useSession } from '@/session/session'
import { latestEntryDate, signOffPreview } from './state'

export function SignOffDialog({
  clientId,
  books,
  open,
  onOpenChange,
}: {
  clientId: string
  books: BooksStatus
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const entries = useQuery({ ...journal(clientId), enabled: open })
  const invalidate = useInvalidateClient(clientId)
  const queryClient = useQueryClient()
  const [text, setText] = useState('')
  const [marking, setMarking] = useState(false)
  const [markError, setMarkError] = useState<string | null>(null)

  const latest = entries.data ? latestEntryDate(entries.data) : null
  // Start from the latest entry; the person may edit it. Reset each time the dialog opens.
  useEffect(() => {
    if (open) setText('')
  }, [open])
  useEffect(() => {
    if (open && latest && text === '') setText(formatDate(latest))
  }, [open, latest, text])

  const date = parseDate(text)
  const preview = entries.data && date ? signOffPreview(entries.data, date, books.signed_off_through) : null
  const mayMark = can('journal.correct') && !!client.data?.can_post

  async function markChecked() {
    setMarking(true)
    setMarkError(null)
    try {
      await raw.post(`${V1}/clients/${clientId}/books/mark-reviewed/`, {})
      await Promise.all([invalidate(), queryClient.invalidateQueries({ queryKey: clientKeys.part(clientId, 'journal') })])
      toast.success('Assistant entries marked as checked')
    } catch (e) {
      setMarkError(messageOf(e))
    } finally {
      setMarking(false)
    }
  }

  let blockedReason: ReactNode = null
  if (entries.isPending) blockedReason = 'Reading the entries…'
  else if (entries.error) blockedReason = 'The entries could not be loaded, so what would be locked cannot be shown.'
  else if (!date) blockedReason = 'Enter the date as DD-MM-YYYY.'
  else if (preview && preview.unchecked > 0)
    blockedReason = (
      <div className="grid gap-2">
        <p>
          <strong>
            {plural(preview.unchecked, 'entry', 'entries')} posted or changed by the assistant {preview.unchecked === 1 ? 'is' : 'are'} not yet
            checked.
          </strong>{' '}
          The books cannot be signed off through {formatDate(date)} until a person has looked at them.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button asChild size="sm" variant="outline">
            <Link to="/clients/$clientId/daybook" params={{ clientId }}>
              Review them in the Day Book
            </Link>
          </Button>
          {mayMark && (
            <Button size="sm" variant="outline" onClick={() => void markChecked()} disabled={marking}>
              {marking ? 'Marking…' : 'Mark assistant entries as checked'}
            </Button>
          )}
        </div>
        <p className="text-xs text-muted-foreground">Only mark them once you have looked at them in the Day Book (filter “Assistant entries only”).</p>
        {markError && (
          <p role="alert" className="text-destructive">
            {markError}
          </p>
        )}
      </div>
    )

  return (
    <Confirm
      open={open}
      onOpenChange={onOpenChange}
      title="Sign off the books?"
      confirmLabel="Sign off"
      note="optional"
      blockedReason={blockedReason}
      onConfirm={async (note) => {
        if (!date) throw new Error('Enter the date as DD-MM-YYYY.')
        await raw.post<BooksStatus>(`${V1}/clients/${clientId}/books/sign-off/`, { note, through: date })
        await invalidate()
        toast.success('Books signed off')
      }}
    >
      <Field label="Sign off through" hint="Defaults to the latest entry. Change it to sign off an earlier month.">
        {(p) => <DateInput {...p} value={text} onChange={(e) => setText(e.target.value)} />}
      </Field>
      {preview && date && (
        <div className="rounded-md border p-3">
          <div className="font-medium text-foreground">
            This locks {plural(preview.vouchers, 'voucher')}
            {books.signed_off_through ? ` after ${formatDate(books.signed_off_through)}` : ''} up to {formatDate(date)}
          </div>
          <dl className="num mt-1 grid grid-cols-[auto_1fr] gap-x-4">
            <dt>Total Dr</dt>
            <dd className="text-right">{formatPaise(preview.drPaise)}</dd>
            <dt>Total Cr</dt>
            <dd className="text-right">{formatPaise(preview.crPaise)}</dd>
            <dt>Assistant entries not yet checked</dt>
            <dd className="text-right">{preview.unchecked}</dd>
          </dl>
        </div>
      )}
      <p>
        Those entries can no longer be changed or removed, only adjusted by a correcting entry after that date. Voucher numbers are renumbered
        so they run without gaps, per voucher type and year.
      </p>
    </Confirm>
  )
}
