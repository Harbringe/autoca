// The client's bank accounts and every statement on file.
//
// Upload is at the top because it is the first thing done here. Below it, each account with
// the balance it opened at, and each statement with its period and totals, which are the
// figures a CA ties to the bank's own document. From a statement: look at its rows, export it
// to Tally, or take it back out if it was the wrong file.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Download, Eye, FileUp, Pencil, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { statementRows } from '@/api/queries/books'
import { bankAccounts, statements, useInvalidateClient, V1 } from '@/api/queries/clients'
import type { BankAccount, Statement, TallyExport } from '@/api/types'
import { Confirm } from '@/components/ca/Confirm'
import { Money } from '@/components/ca/Money'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { tbl } from '@/components/ui/controls'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, plural } from '@/lib/format'
import { saveText } from '@/platform/download'
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

  async function exportTally(s: Statement) {
    try {
      const out = await raw.get<TallyExport>(`${V1}/statements/${s.id}/tally-export/`)
      await saveText(`tally-${s.bank_account_label.replace(/\W+/g, '-')}-${s.period_start}-to-${s.period_end}.xml`, out.xml, 'application/xml')
      toast.success(`Exported ${plural(out.voucher_count, 'voucher')} for Tally`, {
        description: out.unapproved
          ? `${plural(out.unapproved, 'row')} from this statement ${out.unapproved === 1 ? 'is' : 'are'} not posted yet and ${out.unapproved === 1 ? 'is' : 'are'} not in the file.`
          : 'Import it in Tally under Gateway › Import › Vouchers. Re-importing updates, it does not duplicate.',
      })
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  return (
    <div className="grid gap-5">
      {can('document.upload') && (
        <Card className="flex flex-wrap items-center justify-between gap-4 p-5">
          <div>
            <div className="font-medium">Add a bank statement</div>
            <p className="text-sm text-muted-foreground">
              The PDF from net banking, any bank. Its rows are checked against the running balance, then placed by rules and the
              assistant.
            </p>
          </div>
          <Button onClick={upload.open}>
            <FileUp /> Upload bank statement
          </Button>
        </Card>
      )}

      <section className="grid gap-2">
        <h2 className="text-base font-semibold">Bank accounts</h2>
        {accounts.isPending ? (
          <Spinner />
        ) : accounts.error ? (
          <ErrorState error={accounts.error} retry={() => void accounts.refetch()} />
        ) : accounts.data.results.length === 0 ? (
          <EmptyState title="No bank accounts yet">An account is set up from the first statement uploaded for it.</EmptyState>
        ) : (
          <div className={tbl.wrap}>
            <table className={tbl.table}>
              <thead className={tbl.head}>
                <tr>
                  <th className={tbl.th}>Account</th>
                  <th className={tbl.th}>IFSC</th>
                  <th className={tbl.th}>Ledger in Tally</th>
                  <th className={tbl.thNum}>Opening balance</th>
                  <th className={tbl.th}>As at</th>
                  <th className={tbl.th}></th>
                </tr>
              </thead>
              <tbody>
                {accounts.data.results.map((a) => (
                  <tr key={a.id} className={tbl.row}>
                    <td className={`${tbl.td} font-medium`}>{a.label}</td>
                    <td className={`${tbl.td} font-mono text-xs text-muted-foreground`}>{a.ifsc || '—'}</td>
                    <td className={tbl.td}>{a.ledger_name}</td>
                    <td className={tbl.tdNum}>
                      {a.has_opening_balance ? <Money display={a.opening_balance_display} /> : <Badge tone="warning">Not confirmed</Badge>}
                    </td>
                    <td className={`${tbl.td} num`}>{formatDate(a.opening_as_of)}</td>
                    <td className={`${tbl.td} text-right`}>
                      {can('ledger.manage') && (
                        <span className="flex justify-end gap-1">
                          <Button size="sm" variant={a.has_opening_balance ? 'ghost' : 'primary'} onClick={() => setOpening(a)}>
                            {a.has_opening_balance ? 'Change opening' : 'Confirm opening'}
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setRenaming(a)} aria-label={`Rename ledger for ${a.label}`}>
                            <Pencil />
                          </Button>
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="grid gap-2">
        <h2 className="text-base font-semibold">Statements on file</h2>
        {stmts.isPending ? (
          <Spinner />
        ) : stmts.error ? (
          <ErrorState error={stmts.error} retry={() => void stmts.refetch()} />
        ) : stmts.data.results.length === 0 ? (
          <EmptyState
            title="No statements yet"
            action={
              can('document.upload') && (
                <Button onClick={upload.open}>
                  <FileUp /> Upload the first statement
                </Button>
              )
            }
          >
            Everything in the books starts from a bank statement.
          </EmptyState>
        ) : (
          <div className={tbl.wrap}>
            <table className={tbl.table}>
              <thead className={tbl.head}>
                <tr>
                  <th className={tbl.th}>Period</th>
                  <th className={tbl.th}>Account</th>
                  <th className={tbl.thNum}>Rows</th>
                  <th className={tbl.thNum}>Opening</th>
                  <th className={tbl.thNum}>Withdrawals</th>
                  <th className={tbl.thNum}>Deposits</th>
                  <th className={tbl.thNum}>Closing</th>
                  <th className={tbl.th}></th>
                </tr>
              </thead>
              <tbody>
                {[...stmts.data.results]
                  .sort((x, y) => y.period_end.localeCompare(x.period_end))
                  .map((s) => (
                    <tr key={s.id} className={tbl.row}>
                      <td className={`${tbl.td} num whitespace-nowrap`}>
                        {formatDate(s.period_start)} to {formatDate(s.period_end)}
                        <div className="max-w-56 truncate text-xs text-muted-foreground" title={s.document.original_filename}>
                          {s.document.original_filename}
                        </div>
                      </td>
                      <td className={tbl.td}>{s.bank_account_label}</td>
                      <td className={tbl.tdNum}>{s.transaction_count}</td>
                      <td className={tbl.tdNum}><Money display={s.opening_balance_display} /></td>
                      <td className={tbl.tdNum}><Money display={s.total_debit_display} /></td>
                      <td className={tbl.tdNum}><Money display={s.total_credit_display} /></td>
                      <td className={tbl.tdNum}><Money display={s.closing_balance_display} /></td>
                      <td className={`${tbl.td} text-right`}>
                        <span className="flex justify-end gap-1">
                          <Button size="sm" variant="ghost" onClick={() => setViewing(s)}>
                            <Eye /> Rows
                          </Button>
                          {can('report.view') && (
                            <Button size="sm" variant="ghost" onClick={() => void exportTally(s)}>
                              <Download /> Tally XML
                            </Button>
                          )}
                          {can('statement.delete') && (
                            <Button size="sm" variant="ghost" onClick={() => setRemoving(s)} aria-label="Remove statement">
                              <Trash2 />
                            </Button>
                          )}
                        </span>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
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
        <div className="max-h-[65vh] overflow-auto rounded-md border">
          {rows.isPending ? (
            <Spinner />
          ) : rows.error ? (
            <ErrorState error={rows.error} />
          ) : (
            <table className={tbl.table}>
              <thead className={`${tbl.head} sticky top-0`}>
                <tr>
                  <th className={tbl.thNum}>#</th>
                  <th className={tbl.th}>Date</th>
                  <th className={tbl.th}>Narration</th>
                  <th className={tbl.thNum}>Withdrawal</th>
                  <th className={tbl.thNum}>Deposit</th>
                  <th className={tbl.thNum}>Balance</th>
                </tr>
              </thead>
              <tbody>
                {rows.data.map((r) => (
                  <tr key={r.id} className={tbl.row}>
                    <td className={`${tbl.tdNum} text-muted-foreground`}>{r.row_number}</td>
                    <td className={`${tbl.td} num whitespace-nowrap`}>{formatDate(r.value_date)}</td>
                    <td className={`${tbl.td} max-w-md truncate`} title={r.narration}>{r.narration}</td>
                    <td className={tbl.tdNum}>{r.is_debit ? <Money display={r.amount_display} /> : ''}</td>
                    <td className={tbl.tdNum}>{!r.is_debit ? <Money display={r.amount_display} /> : ''}</td>
                    <td className={tbl.tdNum}><Money display={r.balance_display} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
