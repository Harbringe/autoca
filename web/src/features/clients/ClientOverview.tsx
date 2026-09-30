// Where this client's books stand, as the list of steps a CA works through.
//
// Six steps, from statement to signature. Each says whether it is done, what is left, and has
// one button that goes to exactly where the next thing is done. The first step not yet done
// is the one highlighted: a new joiner can open a client and know what to do without asking.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Check } from 'lucide-react'
import type { ReactNode } from 'react'
import { bankAccounts, booksStatus, clientDetail, reviewSummary, statements } from '@/api/queries/clients'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { useUpload } from '@/features/statements/UploadDialog'
import { unsignedThrough } from '@/features/books/state'
import { formatDate, plural } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'

interface Step {
  title: string
  done: boolean
  status: ReactNode
  action?: ReactNode
}

export function ClientOverview({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const upload = useUpload()
  const client = useQuery(clientDetail(clientId))
  const stmts = useQuery({ ...statements(clientId), enabled: can('document.view') })
  const accounts = useQuery(bankAccounts(clientId))
  const summary = useQuery({ ...reviewSummary(clientId), enabled: can('transaction.view') })
  const books = useQuery({ ...booksStatus(clientId), enabled: can('report.view') })

  if (stmts.isPending || accounts.isPending || summary.isPending || books.isPending) return <Spinner label="Working out where the books stand…" />

  const statementCount = stmts.data?.count ?? 0
  const latest = stmts.data?.results.reduce<string | null>((max, s) => (!max || s.period_end > max ? s.period_end : max), null)
  const needOpening = (accounts.data?.results ?? []).filter((a) => !a.has_opening_balance)
  const unresolved = summary.data?.unresolved ?? 0
  const pending = summary.data?.pending_approval ?? 0
  const b = books.data
  const hasStatements = statementCount > 0
  const unchecked = b ? b.ai_posted + b.ai_revised : 0
  // Posted since the last sign-off and not yet sent: the review steps are open again.
  const unsigned = b ? unsignedThrough(b, latest ?? null) : null
  const link = (to: string, label: string, search?: Record<string, string>) => (
    <Button asChild size="sm" variant="outline">
      <Link to={to} params={{ clientId }} search={search as never}>
        {label}
      </Link>
    </Button>
  )

  const steps: Step[] = [
    {
      title: 'Upload bank statements',
      done: hasStatements,
      status: hasStatements
        ? `${plural(statementCount, 'statement')} on file${latest ? `, up to ${formatDate(latest)}` : ''}.`
        : 'No statements yet. Download the client’s bank statement PDF from net banking and upload it.',
      action: can('document.upload') && (
        <Button size="sm" variant={hasStatements ? 'outline' : 'primary'} onClick={upload.open}>
          {hasStatements ? 'Upload the next one' : 'Upload a statement'}
        </Button>
      ),
    },
    {
      title: 'Confirm opening balances',
      done: hasStatements && needOpening.length === 0,
      status: !hasStatements
        ? 'Each bank account needs the balance it started with. Asked for after the first upload.'
        : needOpening.length
          ? `Not confirmed for ${needOpening.map((a) => a.label).join(', ')}. Bank reconciliation is meaningless until it is.`
          : 'Confirmed for every bank account.',
      action: needOpening.length > 0 && link('/clients/$clientId/statements', 'Confirm'),
    },
    {
      title: 'Place every transaction in a ledger',
      done: hasStatements && unresolved === 0,
      status: !hasStatements
        ? 'After upload, rules and the assistant place what they can; you decide the rest.'
        : unresolved
          ? `${plural(unresolved, 'transaction')} still ${unresolved === 1 ? 'needs' : 'need'} a ledger.`
          : 'Every transaction has a ledger.',
      action: unresolved > 0 && link('/clients/$clientId/review', 'Review', { stage: 'unresolved' }),
    },
    {
      title: 'Post to the Day Book',
      done: hasStatements && unresolved === 0 && pending === 0 && unchecked === 0,
      status: !hasStatements
        ? 'Placed transactions become journal entries once posted.'
        : pending
          ? `${plural(pending, 'transaction')} placed and ready to post${summary.data?.bulk_approvable ? `, ${summary.data.bulk_approvable} of them high-confidence` : ''}.`
          : unresolved
            ? 'Nothing ready to post yet.'
            : unchecked
              ? `${plural(unchecked, 'entry', 'entries')} posted by the assistant, not yet checked. Look at them in the Day Book and mark them as checked; the books cannot be signed off until then.`
              : 'Everything is posted and checked.',
      action:
        pending > 0
          ? link('/clients/$clientId/review', 'Post', { stage: 'pending_approval' })
          : unchecked > 0 && link('/clients/$clientId/daybook', 'Check them'),
    },
    {
      title: 'Send for review',
      done: hasStatements && !!b && (b.review_pending || !unsigned),
      status: !b
        ? '—'
        : b.review_pending
          ? `Sent by ${b.requested_by}.`
          : b.returned_note && b.history[0]?.action === 'RETURNED'
            ? `Returned with a note: “${b.returned_note}”`
            : b.waiting
              ? `Possible once nothing is waiting (${b.waiting} now).`
              : b.signed_off_through && unsigned
                ? `Entries after ${formatDate(b.signed_off_through)} (the last sign-off) have not been sent for review.`
                : 'Ready to send.',
      action: b && !b.review_pending && b.can_request && link('/clients/$clientId/books', 'Send for review'),
    },
    {
      title: client.data?.lead ? 'Senior CA signs off' : 'A firm administrator signs off (no senior CA assigned)',
      done: hasStatements && !!b?.signed_off_through && !b.review_pending && !unsigned,
      status: b?.signed_off_through
        ? `Signed off through ${formatDate(b.signed_off_through)}. Entries up to that date are locked.${unsigned ? ` Statements run to ${formatDate(unsigned)}.` : ''}`
        : 'Once signed, the period is locked and voucher numbers are made final.',
      action: b?.review_pending && b.can_sign_off && link('/clients/$clientId/books', 'Review and sign off'),
    },
  ]
  const current = steps.findIndex((s) => !s.done)

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <Card className="p-2">
        <ol className="divide-y">
          {steps.map((step, i) => (
            <li key={step.title} className={cn('flex items-start gap-4 rounded-md p-4', i === current && 'border border-accent-edge bg-accent')}>
              <span
                className={cn(
                  'grid size-7 shrink-0 place-items-center rounded-full border text-[13px] font-semibold',
                  step.done && 'border-success bg-success text-primary-foreground',
                  i === current && 'border-primary bg-primary text-primary-foreground',
                )}
                aria-hidden
              >
                {step.done ? <Check className="size-4" /> : i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="font-medium">
                  {step.title}
                  {i === current && <span className="ml-2 text-xs font-normal text-muted-foreground">Next step</span>}
                  <span className="sr-only">{step.done ? ' (done)' : ''}</span>
                </div>
                <p className="text-sm text-muted-foreground">{step.status}</p>
              </div>
              {step.action && <div className="shrink-0">{step.action}</div>}
            </li>
          ))}
        </ol>
      </Card>

      <div className="grid content-start gap-4">
        <Card className="p-4 text-sm">
          <div className="mb-2 font-medium">Client details</div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            <dt className="text-muted-foreground">Financial year starts</dt>
            <dd className="num text-right">{formatDate(client.data?.fy_start)}</dd>
            <dt className="text-muted-foreground">Bank accounts</dt>
            <dd className="text-right">{accounts.data?.count ?? 0}</dd>
          </dl>
          {client.data?.business_profile && <p className="mt-3 text-muted-foreground">{client.data.business_profile}</p>}
        </Card>
        {b && (b.ai_posted > 0 || b.ai_revised > 0) && (
          <Card className="p-4 text-sm">
            <div className="font-medium">Assistant entries to check</div>
            <p className="text-muted-foreground">
              {plural(b.ai_posted + b.ai_revised, 'entry', 'entries')} were posted or changed by the assistant without a person looking. Sign-off is refused until they are checked. They are
              marked in the Day Book.
            </p>
            <div className="mt-2">{link('/clients/$clientId/daybook', 'Open Day Book')}</div>
          </Card>
        )}
      </div>
    </div>
  )
}
