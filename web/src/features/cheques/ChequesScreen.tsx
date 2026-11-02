// The cheque register: cheques the client has issued and received, post-dated ones, and where each stands. Records and prints; books nothing.

import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'
import { messageOf } from '@/api/errors'
import { chequeAccounts, cheques, pdcSummary, useAddCheque, useRemoveCheque, useSetChequeStatus, type Cheque, type ChequeStatus } from '@/api/queries/cheques'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, formatPaise, parseRupees } from '@/lib/format'
import { toast } from '@/lib/toast'
import { PaymentFileCard } from './PaymentFileCard'

const money = (paise: number) => formatPaise(paise, { symbol: false })
const today = () => new Date().toISOString().slice(0, 10)

function AddCheque({ clientId }: { clientId: string }) {
  const accounts = useQuery(chequeAccounts(clientId))
  const add = useAddCheque(clientId)
  const [account, setAccount] = useState('')
  const [direction, setDirection] = useState<'ISSUED' | 'RECEIVED'>('ISSUED')
  const [number, setNumber] = useState('')
  const [date, setDate] = useState(today())
  const [amount, setAmount] = useState('')
  const [payee, setPayee] = useState('')
  const chosen = account || accounts.data?.[0]?.id || ''

  function submit() {
    const paise = parseRupees(amount)
    if (paise === null || paise <= 0) return void toast.error('Give the amount in rupees, like 25000 or 25000.50.')
    add.mutate(
      { bank_account: chosen, direction, number: number.trim(), cheque_date: date, amount_paise: paise, payee_name: payee.trim() },
      { onSuccess: () => { setNumber(''); setAmount(''); setPayee(''); toast.success('Cheque recorded') }, onError: (e) => toast.error(messageOf(e)) },
    )
  }

  if (accounts.data && accounts.data.length === 0) return <p className="text-sm text-muted-foreground">Add a bank account for this client before recording cheques.</p>
  return (
    <div className="flex flex-wrap items-end gap-2" role="group" aria-label="Record a cheque">
      <label className="grid gap-0.5 text-xs text-muted-foreground">
        <span aria-hidden>Bank account</span>
        <select aria-label="Bank account" className="h-9 rounded-md border border-border-strong bg-transparent px-2 text-sm text-foreground" value={chosen} onChange={(e) => setAccount(e.target.value)}>
          {(accounts.data ?? []).map((a) => (
            <option key={a.id} value={a.id}>{a.label}</option>
          ))}
        </select>
      </label>
      <label className="grid gap-0.5 text-xs text-muted-foreground">
        <span aria-hidden>Direction</span>
        <select aria-label="Direction" className="h-9 rounded-md border border-border-strong bg-transparent px-2 text-sm text-foreground" value={direction} onChange={(e) => setDirection(e.target.value as 'ISSUED' | 'RECEIVED')}>
          <option value="ISSUED">Issued</option>
          <option value="RECEIVED">Received</option>
        </select>
      </label>
      <label className="grid gap-0.5 text-xs text-muted-foreground">
        <span aria-hidden>Cheque no.</span>
        <Input aria-label="Cheque number" className="w-28" value={number} onChange={(e) => setNumber(e.target.value)} />
      </label>
      <label className="grid gap-0.5 text-xs text-muted-foreground">
        <span aria-hidden>Cheque date</span>
        <input aria-label="Cheque date" type="date" className="h-9 rounded-md border border-border-strong bg-transparent px-2 text-sm text-foreground" value={date} onChange={(e) => setDate(e.target.value)} />
      </label>
      <label className="grid gap-0.5 text-xs text-muted-foreground">
        <span aria-hidden>Amount (₹)</span>
        <Input aria-label="Cheque amount" inputMode="decimal" className="w-32" value={amount} onChange={(e) => setAmount(e.target.value)} />
      </label>
      <label className="grid gap-0.5 text-xs text-muted-foreground">
        <span aria-hidden>Payee or drawer</span>
        <Input aria-label="Payee" className="w-56" value={payee} onChange={(e) => setPayee(e.target.value)} />
      </label>
      <Button loading={add.isPending} disabled={!chosen || !number.trim() || !amount.trim()} onClick={submit}>
        Record cheque
      </Button>
    </div>
  )
}

export function ChequesScreen({ clientId, mayEdit }: { clientId: string; mayEdit: boolean }) {
  const list = useQuery(cheques(clientId))
  const pdc = useQuery(pdcSummary(clientId))
  const setStatus = useSetChequeStatus(clientId)
  const remove = useRemoveCheque(clientId)
  const [direction, setDirection] = useState('')
  const [status, setStatus2] = useState('')
  if (list.isPending) return <Spinner />
  if (list.error) return <ErrorState error={list.error} retry={() => void list.refetch()} />
  const rows = list.data.filter((c) => (!direction || c.direction === direction) && (!status || c.status === status))
  const act = (c: Cheque, next: ChequeStatus) => setStatus.mutate({ id: c.id, status: next }, { onError: (e) => toast.error(messageOf(e)) })

  return (
    <div className="grid gap-4 text-sm">
      <section aria-label="Post-dated cheques" className="grid gap-1 rounded-md border border-line p-3">
        <h2 className="text-[15px] font-semibold text-heading">Post-dated cheques</h2>
        {pdc.data && pdc.data.issued_paise + pdc.data.received_paise === 0 ? (
          <p className="text-muted-foreground">No post-dated cheques are waiting.</p>
        ) : (
          pdc.data && (
            <>
              <p>
                Issued, waiting to be presented: <strong>{money(pdc.data.issued_paise)}</strong>. Received, waiting to be deposited: <strong>{money(pdc.data.received_paise)}</strong>.
              </p>
              <ul className="text-muted-foreground">
                {pdc.data.by_month.map((m) => (
                  <li key={m.month}>{m.month}: issued {money(m.issued_paise)}, received {money(m.received_paise)}</li>
                ))}
              </ul>
            </>
          )
        )}
        {pdc.data && pdc.data.due_soon.length > 0 && (
          <p role="status">Falling due in the next seven days: {pdc.data.due_soon.map((c) => `${c.number} (${money(c.amount_paise)}, ${formatDate(c.cheque_date)})`).join('; ')}.</p>
        )}
        {pdc.data && pdc.data.stale.length > 0 && (
          <p role="status">More than three months past their date and still pending: {pdc.data.stale.map((c) => c.number).join(', ')}. A bank will not honour them.</p>
        )}
      </section>

      {mayEdit && <AddCheque clientId={clientId} />}
      {mayEdit && <PaymentFileCard clientId={clientId} />}

      <div className="flex items-center gap-2">
        <select aria-label="Show direction" className="h-9 rounded-md border border-border-strong bg-transparent px-2" value={direction} onChange={(e) => setDirection(e.target.value)}>
          <option value="">Issued and received</option>
          <option value="ISSUED">Issued</option>
          <option value="RECEIVED">Received</option>
        </select>
        <select aria-label="Show status" className="h-9 rounded-md border border-border-strong bg-transparent px-2" value={status} onChange={(e) => setStatus2(e.target.value)}>
          <option value="">Any status</option>
          <option value="PENDING">Not yet presented</option>
          <option value="CLEARED">Cleared</option>
          <option value="BOUNCED">Bounced</option>
          <option value="CANCELLED">Cancelled</option>
        </select>
      </div>

      {rows.length === 0 ? (
        <EmptyState title="No cheques here">Record a cheque above, or change the filters.</EmptyState>
      ) : (
        <table className="w-full" aria-label="Cheques">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="py-1 font-medium">No.</th>
              <th className="py-1 font-medium">Date</th>
              <th className="py-1 font-medium">Direction</th>
              <th className="py-1 font-medium">Payee or drawer</th>
              <th className="py-1 font-medium">Bank</th>
              <th className="py-1 text-right font-medium">Amount</th>
              <th className="py-1 font-medium">Status</th>
              <th className="py-1" />
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="border-t border-border-strong">
                <td className="py-1">{c.number}</td>
                <td className="py-1">
                  {formatDate(c.cheque_date)}
                  {c.is_post_dated && <span className="ml-1 text-xs text-muted-foreground">post-dated</span>}
                </td>
                <td className="py-1">{c.direction === 'ISSUED' ? 'Issued' : 'Received'}</td>
                <td className="py-1">{c.print_name}</td>
                <td className="py-1">{c.bank_label}</td>
                <td className="py-1 text-right tabular-nums">{money(c.amount_paise)}</td>
                <td className="py-1">
                  {c.status_display}
                  {c.status_on && <span className="ml-1 text-xs text-muted-foreground">{formatDate(c.status_on)}</span>}
                  {c.is_stale && <span className="ml-1 text-xs">· stale</span>}
                </td>
                <td className="whitespace-nowrap py-1 text-right">
                  {c.direction === 'ISSUED' && (
                    <Button asChild size="sm" variant="ghost">
                      <Link to="/clients/$clientId/print" params={{ clientId }} search={{ cheque: c.id }} aria-label={`Print cheque ${c.number}`}>
                        Print
                      </Link>
                    </Button>
                  )}
                  {mayEdit && c.status === 'PENDING' && (
                    <>
                      <Button size="sm" variant="ghost" aria-label={`Mark cheque ${c.number} cleared`} onClick={() => act(c, 'CLEARED')}>Cleared</Button>
                      <Button size="sm" variant="ghost" aria-label={`Mark cheque ${c.number} bounced`} onClick={() => act(c, 'BOUNCED')}>Bounced</Button>
                      <Button size="sm" variant="ghost" aria-label={`Cancel cheque ${c.number}`} onClick={() => act(c, 'CANCELLED')}>Cancel</Button>
                      <Button size="sm" variant="ghost" aria-label={`Remove cheque ${c.number}`} onClick={() => remove.mutate(c.id, { onError: (e) => toast.error(messageOf(e)) })}>Remove</Button>
                    </>
                  )}
                  {mayEdit && c.status !== 'PENDING' && (
                    <Button size="sm" variant="ghost" aria-label={`Reopen cheque ${c.number}`} onClick={() => act(c, 'PENDING')}>Reopen</Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
