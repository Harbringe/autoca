// The client's bank accounts and every statement on file.
//
// Upload is at the top because it is the first thing done here. Below it, each account with
// the balance it opened at, and each statement with its period and totals, which are the
// figures a CA ties to the bank's own document. From a statement: look at its rows, export it
// to Tally, or take it back out if it was the wrong file.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Eye, FileUp, Pencil, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { statementRows } from '@/api/queries/books'
import { bankAccounts, reviewSummary, statements, useInvalidateClient, V1 } from '@/api/queries/clients'
import type { BankAccount, Statement } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { Money } from '@/components/ca/Money'
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
import { OpeningBalance, useUpload } from './UploadDialog'

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
  const rowsOnFile = (stmts.data?.results ?? []).reduce((n, s) => n + s.transaction_count, 0)
  // Rows waiting are the review queue; whatever else is on file has been posted.
  const waiting = summary.data ? summary.data.unresolved + summary.data.pending_approval : 0
  const standing = summary.data ? { posted: Math.max(0, rowsOnFile - waiting), ready: summary.data.pending_approval, needs: summary.data.unresolved } : null

  const accountColumns: Column<BankAccount>[] = [
    { key: 'account', header: 'Account', cell: (a) => <span className="font-medium text-heading">{a.label}</span> },
    { key: 'ifsc', header: 'IFSC', priority: 3, cell: (a) => <span className="font-mono text-xs text-muted-foreground">{a.ifsc || '—'}</span> },
    { key: 'ledger', header: 'Ledger in Tally', priority: 2, cell: (a) => a.ledger_name },
    {
      key: 'opening',
      header: 'Opening balance',
      align: 'right',
      cell: (a) => (a.has_opening_balance ? <Money display={a.opening_balance_display} /> : <Badge tone="attention">Not confirmed</Badge>),
    },
    { key: 'asat', header: 'As at', priority: 2, align: 'right', cell: (a) => formatDate(a.opening_as_of) },
    {
      key: 'actions',
      header: <span className="sr-only">Actions</span>,
      align: 'right',
      cell: (a) =>
        can('ledger.manage') && (
          <span className="flex justify-end gap-1">
            <Button size="sm" variant={a.has_opening_balance ? 'ghost' : 'primary'} onClick={() => setOpening(a)}>
              {a.has_opening_balance ? 'Change opening' : 'Confirm opening'}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setRenaming(a)} aria-label={`Rename ledger for ${a.label}`}>
              <Pencil />
            </Button>
          </span>
        ),
    },
  ]

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
    { key: 'account', header: 'Account', priority: 2, cell: (s) => s.bank_account_label },
    { key: 'rows', header: 'Rows', align: 'right', priority: 2, cell: (s) => s.transaction_count },
    { key: 'opening', header: 'Opening', align: 'right', priority: 3, cell: (s) => <Money display={s.opening_balance_display} /> },
    { key: 'withdrawals', header: 'Withdrawals', align: 'right', cell: (s) => <Money display={s.total_debit_display} /> },
    { key: 'deposits', header: 'Deposits', align: 'right', cell: (s) => <Money display={s.total_credit_display} /> },
    { key: 'closing', header: 'Closing', align: 'right', priority: 3, cell: (s) => <Money display={s.closing_balance_display} /> },
    {
      key: 'actions',
      header: <span className="sr-only">Actions</span>,
      align: 'right',
      cell: (s) => (
        <span className="flex justify-end gap-1">
          <Button size="sm" variant="ghost" onClick={() => setViewing(s)}>
            <Eye /> Rows
          </Button>
          {can('statement.delete') && (
            <Button size="sm" variant="ghost" onClick={() => setRemoving(s)} aria-label={`Remove the statement ${formatDate(s.period_start)} to ${formatDate(s.period_end)}`}>
              <Trash2 />
            </Button>
          )}
        </span>
      ),
    },
  ]

  return (
    <div className="grid gap-5">
      {(standing || can('transaction.view')) && (
        <section aria-labelledby="st-standing" className="grid gap-3 rounded-lg border bg-card p-5">
          <h2 id="st-standing" className="text-[15px] font-semibold text-heading">
            Where the rows stand
          </h2>
          {standing ? (
            <StandingBar {...standing} />
          ) : summary.error ? (
            <ErrorState error={summary.error} retry={() => void summary.refetch()} />
          ) : (
            <div className="skeleton h-8 w-full" aria-hidden />
          )}
          <AssistantStrip clientId={clientId} />
        </section>
      )}

      <section className="grid gap-2" aria-labelledby="st-accounts">
        <h2 id="st-accounts" className="text-[15px] font-semibold text-heading">
          Bank accounts
        </h2>
        {accounts.error ? (
          <ErrorState error={accounts.error} retry={() => void accounts.refetch()} />
        ) : (
          <DataTable
            caption="Bank accounts"
            columns={accountColumns}
            rows={accounts.data?.results}
            loading={accounts.isPending}
            rowKey={(a) => a.id}
            empty={<EmptyState title="No bank accounts yet">An account is set up from the first statement uploaded for it.</EmptyState>}
          />
        )}
      </section>

      <section className="grid gap-2" aria-labelledby="st-files">
        <h2 id="st-files" className="text-[15px] font-semibold text-heading">
          Statements on file
        </h2>
        {stmts.error ? (
          <ErrorState error={stmts.error} retry={() => void stmts.refetch()} />
        ) : (
          <DataTable
            caption="Statements on file"
            columns={statementColumns}
            rows={stmts.data?.results}
            loading={stmts.isPending}
            rowKey={(s) => s.id}
            defaultSort={{ key: 'period', dir: 'desc' }}
            empty={
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
                Upload the PDF from net banking, any bank. Everything in the books starts from a bank statement.
              </EmptyState>
            }
          />
        )}
      </section>

      <Dialog open={!!opening} onOpenChange={(o) => !o && setOpening(null)}>
        <DialogContent aria-describedby={undefined}>
          <DialogHeader>
            <DialogTitle>Opening balance of {opening?.label}</DialogTitle>
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
  const invalidate = useInvalidateClient(clientId)
  async function save() {
    try {
      const r = await raw.patch<{ posted_lines?: number }>(`${V1}/clients/${clientId}/bank-accounts/${account.id}/`, { ledger_name: name.trim() })
      await invalidate()
      toast.success('Ledger renamed', { description: r?.posted_lines ? `${plural(r.posted_lines, 'posted line')} moved with it.` : undefined })
      onClose()
    } catch (e) {
      setError(messageOf(e))
    }
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
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
          <Button onClick={() => void save()} disabled={!name.trim()}>Save</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function StatementRows({ clientId, statement, onClose }: { clientId: string; statement: Statement; onClose: () => void }) {
  const rows = useQuery(statementRows(clientId, statement.id))
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-5xl" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>
            {statement.bank_account_label}: {formatDate(statement.period_start)} to {formatDate(statement.period_end)}
          </DialogTitle>
          <DialogDescription>
            As read from the statement. To decide where these go, use{' '}
            <Link to="/clients/$clientId/review" params={{ clientId }} search={{ stage: 'unresolved' }} className="underline" onClick={onClose}>
              Review
            </Link>
            .
          </DialogDescription>
        </DialogHeader>
        {rows.isPending ? (
          <Spinner />
        ) : rows.error ? (
          <ErrorState error={rows.error} />
        ) : (
          <DataTable
            caption={`Rows of the ${statement.bank_account_label} statement`}
            scrollHeight="65vh"
            rows={rows.data}
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
        )}
      </DialogContent>
    </Dialog>
  )
}
