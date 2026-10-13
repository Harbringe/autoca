// The client's bank accounts and every statement on file.
//
// Upload is at the top because it is the first thing done here. Below it, each account with
// the balance it opened at, and each statement with its period and totals, which are the
// figures a CA ties to the bank's own document. From a statement: look at its rows, export it
// to Tally, or take it back out if it was the wrong file.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { FileUp, Pencil } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { reviewQueue, statementRows } from '@/api/queries/books'
import { bankAccounts, reviewSummary, statements, useInvalidateClient, V1 } from '@/api/queries/clients'
import type { BankAccount, Statement } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { Money } from '@/components/ca/Money'
import { Pager, useFadeOnChange, usePaged } from '@/components/ca/Pager'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { StandingBar } from '@/components/ca/StandingBar'
import { DataTable, type Column } from '@/components/ui/table'
import { AssistantStrip } from '@/features/assistant/AssistantStrip'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, plural } from '@/lib/format'
import { useSession } from '@/session/session'
import { PartiesFound } from './PartiesFound'
import { groupByAccount, rowsHeadline } from './statementGroups'
import { usePageSize } from '@/lib/pageSizes'
import { OpeningBalance, useUpload } from './UploadDialog'
import { reviewStage, waitingByStatement, waitingWords } from './statementReview'

/** The Rows and Delete buttons at the end of a statement row. */
const ROW_BUTTON = 'h-11 rounded-lg px-4 font-semibold text-heading dark:border-border-strong dark:bg-background dark:hover:bg-hover'

export function StatementsScreen({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const upload = useUpload()
  const accounts = useQuery(bankAccounts(clientId))
  const stmts = useQuery(statements(clientId))
  const [opening, setOpening] = useState<BankAccount | null>(null)
  const [renaming, setRenaming] = useState<BankAccount | null>(null)
  const [viewing, setViewing] = useState<Statement | null>(null)
  const [removing, setRemoving] = useState<Statement | null>(null)
  const invalidate = useInvalidateClient(clientId)

  const summary = useQuery({ ...reviewSummary(clientId), enabled: can('transaction.view') })
  // What is waiting in each statement, so each can be reviewed on its own. The same two lists the Review screen reads.
  const needsQueue = useQuery({ ...reviewQueue(clientId, 'unresolved'), enabled: can('transaction.view') })
  const readyQueue = useQuery({ ...reviewQueue(clientId, 'pending_approval'), enabled: can('transaction.view') })
  const waitingBy = useMemo(() => waitingByStatement(needsQueue.data ?? [], readyQueue.data ?? []), [needsQueue.data, readyQueue.data])
  const waitingKnown = !!needsQueue.data && !!readyQueue.data
  const rowsOnFile = (stmts.data?.results ?? []).reduce((n, s) => n + s.transaction_count, 0)
  // Rows waiting are the review queue; whatever else is on file has been posted.
  const waiting = summary.data ? summary.data.unresolved + summary.data.pending_approval : 0
  const standing = summary.data ? { posted: Math.max(0, rowsOnFile - waiting), ready: summary.data.pending_approval, needs: summary.data.unresolved } : null

  const { groups, orphans } = groupByAccount(accounts.data?.results ?? [], stmts.data?.results ?? [])

  const statementColumns: Column<Statement>[] = [
    {
      key: 'period',
      header: 'Period',
      sortValue: (s) => s.period_end,
      cell: (s) => (
        <>
          <span className="num">
            {formatDate(s.period_start)} to {formatDate(s.period_end)}
          </span>
          <div className="max-w-56 truncate text-xs text-muted-foreground" title={s.document.original_filename}>
            {s.document.original_filename}
          </div>
        </>
      ),
    },
    { key: 'rows', header: 'Rows', align: 'right', priority: 2, cell: (s) => s.transaction_count },
    {
      key: 'waiting',
      header: 'To review',
      cell: (s) => {
        if (!can('transaction.view')) return null
        if (!waitingKnown) return <span className="text-faint" aria-hidden>…</span>
        const words = waitingWords(waitingBy.get(s.id))
        return words ? <span className="text-sm">{words}</span> : <span className="text-sm text-muted-foreground">All posted</span>
      },
    },
    { key: 'opening', header: 'Opening', align: 'right', priority: 3, cell: (s) => <span className="font-mono"><Money display={s.opening_balance_display} /></span> },
    { key: 'withdrawals', header: 'Withdrawals', align: 'right', cell: (s) => <span className="font-mono"><Money display={s.total_debit_display} /></span> },
    { key: 'deposits', header: 'Deposits', align: 'right', cell: (s) => <span className="font-mono"><Money display={s.total_credit_display} /></span> },
    { key: 'closing', header: 'Closing', align: 'right', priority: 3, cell: (s) => <span className="font-mono font-semibold text-heading"><Money display={s.closing_balance_display} /></span> },
    {
      key: 'actions',
      header: <span className="sr-only">Actions</span>,
      align: 'right',
      cell: (s) => (
        <span className="flex justify-end gap-1">
          {can('transaction.view') &&
            (waitingKnown && !waitingWords(waitingBy.get(s.id)) ? (
              <Button variant="outline" className={ROW_BUTTON} disabled title="Everything in this statement is posted">
                Review
              </Button>
            ) : (
              <Button asChild variant={waitingKnown ? 'primary' : 'outline'} className={ROW_BUTTON}>
                <Link
                  to="/clients/$clientId/review"
                  params={{ clientId }}
                  // Until what is waiting is known the stage is left to Review, which opens where the work is.
                  search={{ stage: waitingKnown ? reviewStage(waitingBy.get(s.id)) : undefined, statement: s.id }}
                  aria-label={`Review the statement ${formatDate(s.period_start)} to ${formatDate(s.period_end)}`}
                >
                  Review
                </Link>
              </Button>
            ))}
          <Button variant="outline" className={ROW_BUTTON} onClick={() => setViewing(s)}>
            Rows
          </Button>
          {can('statement.delete') && (
            <Button variant="outline" className={ROW_BUTTON} onClick={() => setRemoving(s)} aria-label={`Remove the statement ${formatDate(s.period_start)} to ${formatDate(s.period_end)}`}>
              Delete
            </Button>
          )}
        </span>
      ),
    },
  ]

  return (
    <div className="grid gap-5">
      {(standing || can('transaction.view')) && (
        <section aria-labelledby="st-standing" className="grid gap-4 rounded-xl border border-border-strong bg-surface-2 p-6">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h2 id="st-standing" className="text-xl font-semibold text-heading">
              {standing ? rowsHeadline(rowsOnFile, waiting) : 'Where the rows stand'}
            </h2>
            {standing && <span className="text-sm text-muted-foreground">From {plural(stmts.data?.results.length ?? 0, 'statement')}</span>}
          </div>
          {standing ? (
            <StandingBar {...standing} roomy />
          ) : summary.error ? (
            <ErrorState error={summary.error} retry={() => void summary.refetch()} />
          ) : (
            <div className="skeleton h-8 w-full" aria-hidden />
          )}
          <AssistantStrip clientId={clientId} />
        </section>
      )}

      {accounts.error ? (
        <ErrorState error={accounts.error} retry={() => void accounts.refetch()} />
      ) : stmts.error ? (
        <ErrorState error={stmts.error} retry={() => void stmts.refetch()} />
      ) : accounts.isPending || stmts.isPending ? (
        <Spinner label="Loading bank accounts and statements…" />
      ) : (accounts.data?.results.length ?? 0) === 0 && (stmts.data?.results.length ?? 0) === 0 ? (
        <EmptyState
          title="No statements yet"
          action={
            can('document.upload') && (
              <Button onClick={upload.open}>
                <FileUp /> Upload bank statement
              </Button>
            )
          }
        >
          Upload the PDF from net banking, any bank. Everything in the books starts from a bank statement. An account is set up from the first statement uploaded for it.
        </EmptyState>
      ) : (
        <div className="grid gap-5">
          {groups.map(({ account: a, statements: list }) => (
            <section key={a.id} aria-labelledby={`st-acct-${a.id}`} className="grid gap-4 rounded-xl border border-border-strong bg-surface-2 p-6">
              <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
                <div className="min-w-0">
                  <h2 id={`st-acct-${a.id}`} className="text-[22px] font-semibold leading-tight text-heading">
                    {a.label}
                  </h2>
                  <p className="mt-0.5 text-[13px] text-muted-foreground">
                    {a.ifsc && <span className="num">{a.ifsc} · </span>}Ledger in Tally: {a.ledger_name}
                  </p>
                </div>
                <div className="grid gap-1 sm:justify-items-end">
                  <div className="sm:text-right">
                    <p className="text-xs text-muted-foreground">
                      Opening balance{a.has_opening_balance ? ` as at ${formatDate(a.opening_as_of)}` : ''}
                    </p>
                    <p className="font-mono text-3xl font-semibold text-heading">
                      {a.has_opening_balance ? <Money display={a.opening_balance_display} /> : <Badge tone="attention">Not confirmed</Badge>}
                    </p>
                  </div>
                  {can('ledger.manage') && (
                    <span className="flex gap-1">
                      <Button size="sm" variant={a.has_opening_balance ? 'link' : 'primary'} className={a.has_opening_balance ? 'h-auto px-0 font-semibold underline' : undefined} onClick={() => setOpening(a)}>
                        {a.has_opening_balance ? 'Change opening' : 'Confirm opening'}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setRenaming(a)} aria-label={`Rename ledger for ${a.label}`}>
                        <Pencil />
                      </Button>
                    </span>
                  )}
                </div>
              </div>
              {list.length === 0 ? (
                <p className="rounded-md border border-dashed px-3 py-4 text-sm text-muted-foreground">No statement is on file for this account yet.</p>
              ) : (
                <DataTable
                  caption={`Statements of ${a.label}`}
                  columns={statementColumns}
                  rows={list}
                  rowKey={(s) => s.id}
                  defaultSort={{ key: 'period', dir: 'desc' }}
                  className="border-0 bg-transparent [&_td]:py-3"
                />
              )}
            </section>
          ))}
          {orphans.length > 0 && (
            <section aria-labelledby="st-other" className="grid gap-2">
              <h2 id="st-other" className="text-[15px] font-semibold text-heading">
                Other statements on file
              </h2>
              <DataTable caption="Other statements on file" columns={statementColumns} rows={orphans} rowKey={(s) => s.id} defaultSort={{ key: 'period', dir: 'desc' }} />
            </section>
          )}
        </div>
      )}

      <PartiesFound clientId={clientId} />

      <Dialog open={!!opening} onOpenChange={(o) => !o && setOpening(null)}>
        <DialogContent aria-describedby={undefined} className="max-w-xl gap-5 rounded-2xl p-7">
          <DialogHeader>
            <DialogTitle className="text-2xl">Opening balance of {opening?.label}</DialogTitle>
            <DialogDescription>The balance before the first row on file, as at the day before it.</DialogDescription>
          </DialogHeader>
          {opening && (
            <OpeningBalance
              compact
              clientId={clientId}
              account={opening}
              statement={stmts.data?.results
                .filter((s) => s.bank_account === opening.id)
                .sort((x, y) => x.period_start.localeCompare(y.period_start))[0]}
              onDone={() => {
                toast.success('Opening balance confirmed')
                setOpening(null)
              }}
            />
          )}
        </DialogContent>
      </Dialog>

      {renaming && <RenameLedger clientId={clientId} account={renaming} onClose={() => setRenaming(null)} />}
      {viewing && <StatementRows clientId={clientId} statement={viewing} onClose={() => setViewing(null)} />}

      <Confirm
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title="Remove this statement?"
        confirmLabel="Remove statement"
        destructive
        onConfirm={async () => {
          const r = await raw.delete<{ rows: number; entries: number }>(`${V1}/clients/${clientId}/statements/${removing!.id}/`)
          await invalidate()
          toast.success(`Removed ${plural(r?.rows ?? 0, 'row')} and ${plural(r?.entries ?? 0, 'entry', 'entries')}`)
        }}
      >
        <p>
          {removing && (
            <>
              {removing.bank_account_label}, {formatDate(removing.period_start)} to {formatDate(removing.period_end)}:{' '}
              {plural(removing.transaction_count, 'row')}.
            </>
          )}
        </p>
        <p>
          Its rows and every entry posted from them are removed from the books. Each removed entry is kept in the change log. Rules and
          parties learned from it stay. This is refused if any of its entries are in signed-off books.
        </p>
      </Confirm>
    </div>
  )
}

function RenameLedger({ clientId, account, onClose }: { clientId: string; account: BankAccount; onClose: () => void }) {
  const [name, setName] = useState(account.ledger_name ?? '')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const invalidate = useInvalidateClient(clientId)
  async function save() {
    setSaving(true)
    try {
      const r = await raw.patch<{ posted_lines?: number }>(`${V1}/clients/${clientId}/bank-accounts/${account.id}/`, { ledger_name: name.trim() })
      await invalidate()
      toast.success('Ledger renamed', { description: r?.posted_lines ? `${plural(r.posted_lines, 'posted line')} moved with it.` : undefined })
      onClose()
    } catch (e) {
      setError(messageOf(e))
    } finally {
      setSaving(false)
    }
  }
  return (
    <Dialog open onOpenChange={(o) => !o && !saving && onClose()}>
      <DialogContent aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Ledger name for {account.label}</DialogTitle>
          <DialogDescription>Must match the bank ledger’s name in the client’s Tally company exactly, or Tally creates a second one.</DialogDescription>
        </DialogHeader>
        <Field label="Ledger name" error={error ?? undefined}>
          {(p) => <Input {...p} autoFocus value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void save()} />}
        </Field>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={() => void save()} loading={saving} disabled={!name.trim()}>Save</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function StatementRows({ clientId, statement, onClose }: { clientId: string; statement: Statement; onClose: () => void }) {
  const rows = useQuery(statementRows(clientId, statement.id))
  // A year's statement has hundreds of rows: a hundred at a time keeps the window light.
  const paged = usePaged(rows.data ?? [], statement.id, usePageSize('statements'))
  const bodyRef = useRef<HTMLDivElement>(null)
  useFadeOnChange(bodyRef, paged.page)
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-5xl" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>
            {statement.bank_account_label}: {formatDate(statement.period_start)} to {formatDate(statement.period_end)}
          </DialogTitle>
          <DialogDescription>
            As read from the statement. To decide where these go, use{' '}
            <Link to="/clients/$clientId/review" params={{ clientId }} search={{ stage: 'unresolved', statement: statement.id }} className="underline" onClick={onClose}>
              Review this statement
            </Link>
            .
          </DialogDescription>
        </DialogHeader>
        {rows.isPending ? (
          <Spinner />
        ) : rows.error ? (
          <ErrorState error={rows.error} />
        ) : (
          <>
          <div ref={bodyRef}>
          <DataTable
            caption={`Rows of the ${statement.bank_account_label} statement`}
            scrollHeight="65vh"
            rows={paged.items}
            rowKey={(r) => String(r.id)}
            columns={[
              { key: 'no', header: '#', align: 'right', priority: 2, cell: (r) => <span className="text-muted-foreground">{r.row_number}</span> },
              { key: 'date', header: 'Date', cell: (r) => <span className="num">{formatDate(r.value_date)}</span> },
              { key: 'narration', header: 'Narration', className: 'max-w-md truncate', cell: (r) => <span title={r.narration}>{r.narration}</span> },
              { key: 'w', header: 'Withdrawal', align: 'right', cell: (r) => (r.is_debit ? <Money display={r.amount_display} /> : <span className="text-faint" aria-hidden>–</span>) },
              { key: 'd', header: 'Deposit', align: 'right', cell: (r) => (!r.is_debit ? <Money display={r.amount_display} /> : <span className="text-faint" aria-hidden>–</span>) },
              { key: 'b', header: 'Balance', align: 'right', priority: 2, cell: (r) => <Money display={r.balance_display} /> },
            ]}
          />
          </div>
          <Pager paged={paged} label="Statement rows" className="flex flex-wrap items-center justify-between gap-3 pt-3 text-sm" />
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
