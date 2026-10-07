// The client page: where this client's books stand and how the business is doing, in cards that each
// answer one plain question (see docs/dashboards-plan.md, section 6).
//
// "What is left to do?" is the six steps from statement to signature. Each says whether it is done,
// what is left, and has one button that goes to exactly where the next thing is done. The first step
// not yet done is highlighted and is also the button on the progress card at the top, so a new joiner
// can open a client and know what to do without asking.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Check } from 'lucide-react'
import type { ReactNode } from 'react'
import { bankAccounts, booksStatus, clientDetail, reviewSummary, statements } from '@/api/queries/clients'
import { clientSnapshot } from '@/api/queries/dashboard'
import { DashCard } from '@/components/ca/DashCard'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import { BooksProgressCard } from './BooksProgress'
import { AccountsCard, CostsCard, MoneyKpis, MonthlyCard, OwedCard, ReportTiles, SnapshotFootnote } from './FinancialSnapshot'
import { useUpload } from '@/features/statements/UploadDialog'
import { unsignedThrough } from '@/features/books/state'
import { useFy } from '@/features/shell/useFy'
import { formatDate, plural } from '@/lib/format'
import { isoOf } from '@/lib/period'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { booksProgress, latestEnd, monthCoverage } from './standing'

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
  const snapshotOn = can('journal.view') && (stmts.data?.count ?? 0) > 0
  const snapshot = useQuery({ ...clientSnapshot(clientId, fy), enabled: snapshotOn })

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
      title: 'Confirm each bank account’s starting balance',
      done: hasStatements && needOpening.length === 0,
      status: !hasStatements
        ? 'Each bank account needs the balance it started with. This is asked for after the first upload.'
        : needOpening.length
          ? `Not confirmed for ${needOpening.map((a) => a.label).join(', ')}. Bank reconciliation is meaningless until it is.`
          : 'Confirmed for every bank account.',
      action: needOpening.length > 0 && link('/clients/$clientId/statements', 'Confirm'),
    },
    {
      title: 'Sort every entry into an account',
      done: hasStatements && unresolved === 0,
      status: !hasStatements
        ? 'After upload, the rules and the assistant sort what they can; you decide the rest.'
        : unresolved
          ? `${plural(unresolved, 'entry', 'entries')} still ${unresolved === 1 ? 'needs' : 'need'} an account.`
          : 'Every entry is in an account.',
      action: unresolved > 0 && link('/clients/$clientId/review', 'Sort them', { stage: 'unresolved' }),
    },
    {
      title: 'Record the sorted entries in the books',
      done: hasStatements && unresolved === 0 && pending === 0 && unchecked === 0,
      status: !hasStatements
        ? 'Sorted entries become part of the books once they are recorded.'
        : pending
          ? `${plural(pending, 'entry', 'entries')} sorted and ready to record${summary.data?.bulk_approvable ? `, ${summary.data.bulk_approvable} of them high-confidence` : ''}.`
          : unresolved
            ? 'Nothing is ready to record yet.'
            : unchecked
              ? `${plural(unchecked, 'entry', 'entries')} recorded by the assistant, not yet checked. Look at them in the Day Book and mark them as checked; the books cannot be signed off until then.`
              : 'Everything is recorded and checked.',
      action:
        pending > 0
          ? link('/clients/$clientId/review', 'Record them', { stage: 'pending_approval' })
          : unchecked > 0 && link('/clients/$clientId/daybook', 'Check them'),
    },
    {
      title: 'Send the books to the senior for review',
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
      title: client.data?.lead ? 'Senior CA signs off' : 'A firm administrator signs off (no Senior CA assigned)',
      done: hasStatements && !!b?.signed_off_through && !b.review_pending && !unsigned,
      status: b?.signed_off_through
        ? `Sealed through ${formatDate(b.signed_off_through)}. Entries up to that date are locked.${unsigned ? ` Statements run to ${formatDate(unsigned)}.` : ''}`
        : 'Once signed, the period is locked and voucher numbers are made final.',
      action: b?.review_pending && b.can_sign_off && link('/clients/$clientId/books', 'Review and approve'),
    },
  ]
  const current = steps.findIndex((s) => !s.done)
  const months = monthCoverage(fy, stmts.data?.results ?? [])
  const progress = booksProgress(months, isoOf(new Date()))
  const doneSteps = steps.filter((s) => s.done).length
  const currentStep = current >= 0 ? steps[current]! : null

  return (
    <div className="grid grid-cols-12 gap-4 [&>*]:min-w-0">
      <div className="order-1 col-span-12">
        <BooksProgressCard
          fy={fy}
          months={months}
          progress={progress}
          hasStatements={hasStatements}
          nextTitle={currentStep ? currentStep.title : null}
          nextAction={currentStep?.action ? currentStep.action(true) : null}
          signedOffThrough={b?.signed_off_through}
          upload={can('document.upload') ? <Button onClick={upload.open}>Upload a statement</Button> : null}
        />
      </div>

      {snapshotOn && (
        <div className="order-2 col-span-12 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <MoneyKpis query={snapshot} clientId={clientId} />
        </div>
      )}

      {snapshotOn && (
        <div className="order-4 col-span-12 lg:order-3 lg:col-span-7 xl:col-span-8">
          <MonthlyCard query={snapshot} clientId={clientId} />
        </div>
      )}

      <div className={cn('order-3 col-span-12 lg:order-4', snapshotOn ? 'lg:col-span-5 xl:col-span-4' : 'lg:col-span-12')}>
        <DashCard title="What is left to do?" hint={`${doneSteps} of ${steps.length} steps done`} className="h-full">
          <ol className="-mx-2 grid gap-1">
            {steps.map((step, i) => (
              <li
                key={step.title}
                aria-current={i === current ? 'step' : undefined}
                className={cn('flex flex-wrap items-start gap-x-3 gap-y-2 rounded-lg border border-transparent p-3', i === current && 'border-accent-edge bg-accent')}
              >
                <span
                  className={cn(
                    'grid size-6 shrink-0 place-items-center rounded-full border border-input text-xs font-semibold text-muted-foreground',
                    step.done && 'border-success bg-success text-primary-foreground',
                    i === current && 'border-primary bg-primary text-primary-foreground',
                  )}
                  aria-hidden
                >
                  {step.done ? <Check className="size-3.5" /> : i + 1}
                </span>
                <div className="min-w-0 flex-1 basis-44">
                  <h3 className="flex flex-wrap items-center gap-2 text-sm font-semibold text-heading">
                    {step.title}
                    {i === current && <span className="rounded-sm bg-card px-1.5 text-xs font-medium text-accent-foreground">Next step</span>}
                    {step.done && <span className="sr-only">(done)</span>}
                  </h3>
                  <p className="mt-0.5 text-[13px] leading-5 text-muted-foreground">{step.status}</p>
                </div>
                {step.action && <div className="shrink-0 max-sm:w-full [&>*]:max-sm:w-full">{step.action(false)}</div>}
              </li>
            ))}
          </ol>
        </DashCard>
      </div>

      {snapshotOn && (
        <>
          <div className="order-5 col-span-12 lg:col-span-6 xl:col-span-4">
            <OwedCard query={snapshot} clientId={clientId} />
          </div>
          <div className="order-6 col-span-12 lg:col-span-6 xl:col-span-4">
            <AccountsCard query={snapshot} clientId={clientId} />
          </div>
          <div className="order-7 col-span-12 xl:col-span-4">
            <CostsCard query={snapshot} clientId={clientId} />
          </div>
        </>
      )}

      {can('report.view') && hasStatements && (
        <div className="order-8 col-span-12">
          <ReportTiles clientId={clientId} gst={can('gst.view')} query={snapshot} />
        </div>
      )}

      <div className="order-9 col-span-12 grid gap-4 lg:grid-cols-2 [&>*]:min-w-0">
        <Card className="p-5 text-sm">
          <h2 className="mb-2 text-[15px] font-semibold text-heading">Client details</h2>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5">
            <dt className="text-muted-foreground">Senior CA in charge</dt>
            <dd className="text-right">{client.data?.lead ? client.data.lead.name : <span className="text-accent-foreground">Not assigned</span>}</dd>
            <dt className="text-muted-foreground">Financial year starts</dt>
            <dd className="num text-right">{formatDate(client.data?.fy_start)}</dd>
            <dt className="text-muted-foreground">Bank accounts</dt>
            <dd className="num text-right">{accounts.data?.count ?? 0}</dd>
            <dt className="text-muted-foreground">Signed off to</dt>
            <dd className="num text-right">{b?.signed_off_through ? formatDate(b.signed_off_through) : 'Not yet'}</dd>
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

      {snapshotOn && (
        <div className="order-10 col-span-12">
          <SnapshotFootnote query={snapshot} />
        </div>
      )}
    </div>
  )
}
