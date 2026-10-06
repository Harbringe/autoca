// Where this client's books stand, as the list of steps a CA works through.
//
// Six steps, from statement to signature. Each says whether it is done, what is left, and has
// one button that goes to exactly where the next thing is done. The first step not yet done
// is the one highlighted: a new joiner can open a client and know what to do without asking.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Check, Minus } from 'lucide-react'
import type { ReactNode } from 'react'
import { bankAccounts, booksStatus, clientDetail, reviewSummary, statements } from '@/api/queries/clients'
import { Card } from '@/components/ui/card'
import { StatCard, StatGrid } from '@/components/ui/stat-card'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { FinancialSnapshot } from './FinancialSnapshot'
import { useUpload } from '@/features/statements/UploadDialog'
import { unsignedThrough } from '@/features/books/state'
import { useFy } from '@/features/shell/useFy'
import { formatDate, fyLabel, plural } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { coverageText, latestEnd, monthCoverage, type MonthCover } from './standing'

interface Step {
  title: string
  done: boolean
  status: ReactNode
  /** Given whether this is the current step, so only that step's button is the primary one. */
  action?: false | null | ((primary: boolean) => ReactNode)
}

export function ClientOverview({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const upload = useUpload()
  const client = useQuery(clientDetail(clientId))
  const stmts = useQuery({ ...statements(clientId), enabled: can('document.view') })
  const accounts = useQuery(bankAccounts(clientId))
  const summary = useQuery({ ...reviewSummary(clientId), enabled: can('transaction.view') })
  const books = useQuery({ ...booksStatus(clientId), enabled: can('report.view') })
  const { fy } = useFy()

  if (stmts.isLoading || accounts.isLoading || summary.isLoading || books.isLoading) return <Spinner label="Working out where the books stand…" />

  const statementCount = stmts.data?.count ?? 0
  const latest = latestEnd(stmts.data?.results)
  const needOpening = (accounts.data?.results ?? []).filter((a) => !a.has_opening_balance)
  const unresolved = summary.data?.unresolved ?? 0
  const pending = summary.data?.pending_approval ?? 0
  const b = books.data
  const hasStatements = statementCount > 0
  const unchecked = b ? b.ai_posted + b.ai_revised : 0
  // Posted since the last sign-off and not yet sent: the review steps are open again.
  const unsigned = b ? unsignedThrough(b, latest ?? null) : null
  const link = (to: string, label: string, search?: Record<string, string>) => (primary: boolean) => (
    <Button asChild size="sm" variant={primary ? 'primary' : 'secondary'}>
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
      action: can('document.upload')
        ? (primary: boolean) => (
            <Button size="sm" variant={primary ? 'primary' : 'secondary'} onClick={upload.open}>
              {hasStatements ? 'Upload the next one' : 'Upload a statement'}
            </Button>
          )
        : undefined,
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
                ? `Entries after ${formatDate(b.signed_off_through)} (the last seal) have not been sent for review.`
                : 'Ready to send.',
      action: b && !b.review_pending && b.can_request && link('/clients/$clientId/books', 'Send for review'),
    },
    {
      title: client.data?.lead ? 'Senior CA signs off' : 'A firm administrator signs off (no senior CA assigned)',
      done: hasStatements && !!b?.signed_off_through && !b.review_pending && !unsigned,
      status: b?.signed_off_through
        ? `Sealed through ${formatDate(b.signed_off_through)}. Entries up to that date are locked.${unsigned ? ` Statements run to ${formatDate(unsigned)}.` : ''}`
        : 'Once signed, the period is locked and voucher numbers are made final.',
      action: b?.review_pending && b.can_sign_off && link('/clients/$clientId/books', 'Review and approve'),
    },
  ]
  const current = steps.findIndex((s) => !s.done)
  const months = monthCoverage(fy, stmts.data?.results ?? [])

  return (
    <div className="grid gap-4 [&>*]:min-w-0">
      {can('report.view') && hasStatements && <FinancialSnapshot clientId={clientId} fy={fy} />}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
        <div className="grid gap-4 [&>*]:min-w-0">
          <Card className="p-2">
            <h2 className="sr-only">What is next for these books</h2>
            <ol className="grid gap-1">
              {steps.map((step, i) => (
                <li
                  key={step.title}
                  aria-current={i === current ? 'step' : undefined}
                  className={cn('flex flex-wrap items-start gap-x-4 gap-y-2 rounded-lg border border-transparent p-4', i === current && 'border-accent-edge bg-accent')}
                >
                  <span
                    className={cn(
                      'grid size-7 shrink-0 place-items-center rounded-full border border-input text-[13px] font-semibold text-muted-foreground',
                      step.done && 'border-success bg-success text-primary-foreground',
                      i === current && 'border-primary bg-primary text-primary-foreground',
                    )}
                    aria-hidden
                  >
                    {step.done ? <Check className="size-4" /> : i + 1}
                  </span>
                  <div className="min-w-0 flex-1 basis-56">
                    <h3 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-heading">
                      {step.title}
                      {i === current && <span className="rounded-sm bg-card px-1.5 text-xs font-medium text-accent-foreground">Next step</span>}
                      {step.done && <span className="sr-only">(done)</span>}
                    </h3>
                    <p className="mt-0.5 max-w-prose text-[13px] leading-5 text-muted-foreground">{step.status}</p>
                  </div>
                  {step.action && <div className="shrink-0 max-sm:w-full [&>*]:max-sm:w-full">{step.action(i === current)}</div>}
                </li>
              ))}
            </ol>
          </Card>

          <Card className="p-5">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-[15px] font-semibold text-heading">Statements by month</h2>
              <span className="num text-xs text-muted-foreground">FY {fyLabel(fy)}</span>
            </div>
            <MonthStrip months={months} />
            <p className="mt-3 text-xs text-muted-foreground">{coverageText(months)}</p>
          </Card>
        </div>

        <div className="grid content-start gap-4">
          <Card className="p-5 text-sm">
            <h2 className="mb-2 text-[15px] font-semibold text-heading">Client details</h2>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5">
              <dt className="text-muted-foreground">Senior CA in charge</dt>
              <dd className="text-right">{client.data?.lead ? client.data.lead.name : <span className="text-accent-foreground">Not assigned</span>}</dd>
              <dt className="text-muted-foreground">Financial year starts</dt>
              <dd className="num text-right">{formatDate(client.data?.fy_start)}</dd>
              <dt className="text-muted-foreground">Bank accounts</dt>
              <dd className="num text-right">{accounts.data?.count ?? 0}</dd>
            </dl>
            {client.data?.business_profile && <p className="mt-3 text-[13px] text-muted-foreground">{client.data.business_profile}</p>}
          </Card>
          {b && unchecked > 0 && (
            <div className="rounded-lg border border-accent-edge bg-accent p-4 text-sm text-accent-foreground">
              <h2 className="font-semibold">Assistant entries to check</h2>
              <p className="mt-1">
                {plural(unchecked, 'entry', 'entries')} {unchecked === 1 ? 'was' : 'were'} posted or changed by the assistant without a person looking. Sign-off is refused until they are checked.
              </p>
              <div className="mt-3">{link('/clients/$clientId/daybook', 'Open Day Book')(false)}</div>
            </div>
          )}
        </div>
      </div>

      <section aria-labelledby="glance">
        <h2 id="glance" className="mb-2 text-[15px] font-semibold text-heading">
          Books at a glance
        </h2>
        <StatGrid>
          <StatCard
            label="Rows to place"
            value={unresolved}
            note="No ledger yet"
            to={unresolved ? '/clients/$clientId/review' : undefined}
            params={{ clientId }}
            search={{ stage: 'unresolved' }}
            tone={unresolved ? 'attention' : 'plain'}
          />
          <StatCard
            label="Ready to post"
            value={pending}
            note="Placed, waiting for you"
            to={pending ? '/clients/$clientId/review' : undefined}
            params={{ clientId }}
            search={{ stage: 'pending_approval' }}
          />
          <StatCard
            label="Assistant entries unchecked"
            value={unchecked}
            note="Posted or changed by the assistant"
            to={unchecked ? '/clients/$clientId/daybook' : undefined}
            params={{ clientId }}
            tone={unchecked ? 'attention' : 'plain'}
          />
          <StatCard
            label="Sealed to"
            value={<span className="text-xl">{b?.signed_off_through ? formatDate(b.signed_off_through) : 'Not yet'}</span>}
            note={b?.review_pending ? 'A sign-off is waiting' : undefined}
            to="/clients/$clientId/books"
            params={{ clientId }}
          />
        </StatGrid>
      </section>
    </div>
  )
}

const COVER_LABEL = { full: 'a statement covers this month', partial: 'a statement covers part of this month', none: 'no statement' } as const

/** Twelve months, April to March. Shape as well as fill: a tick, a half, a dash. The sentence below it is the text alternative. */
function MonthStrip({ months }: { months: MonthCover[] }) {
  return (
    <ol className="mt-3 grid grid-cols-6 gap-2 sm:grid-cols-12" aria-hidden>
      {months.map((m) => (
        <li key={m.start} className="grid justify-items-center gap-1" title={`${m.label}: ${COVER_LABEL[m.coverage]}`}>
          <span
            className={cn(
              'grid h-8 w-full place-items-center rounded-md border',
              m.coverage === 'full' && 'border-primary bg-primary text-primary-foreground',
              m.coverage === 'partial' && 'border-primary bg-[linear-gradient(90deg,var(--primary)_50%,transparent_50%)]',
              m.coverage === 'none' && 'border-input text-faint',
            )}
          >
            {m.coverage === 'full' ? <Check className="size-4" /> : m.coverage === 'none' ? <Minus className="size-4" /> : null}
          </span>
          <span className="text-xs text-muted-foreground">{m.label}</span>
        </li>
      ))}
    </ol>
  )
}
