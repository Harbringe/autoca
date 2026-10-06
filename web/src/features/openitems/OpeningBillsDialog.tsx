// Break a party's imported opening balance into the invoices it is made of.
//
// The Tally import brings one number per supplier or customer. Listing the invoices behind it lets payments settle against
// what is really outstanding and lets the party's ledger agree with its bills. The server checks it all: the invoices may
// not add up to more than is left, and each must be dated before the balance. Nothing is posted as a journal entry.

import { useQuery } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { messageOf } from '@/api/errors'
import { partyOpening, useBreakDownOpening } from '@/api/queries/bills'
import { Money } from '@/components/ca/Money'
import { ErrorState } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { DateInput } from '@/components/ui/date-input'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { formatPaise, parseDate, parseRupees } from '@/lib/format'

interface Row {
  reference: string
  date: string
  amount: string
}

const blank = (): Row => ({ reference: '', date: '', amount: '' })

export function OpeningBillsDialog({
  clientId,
  partyId,
  partyName,
  onClose,
}: {
  clientId: string
  partyId: string
  partyName: string
  onClose: () => void
}) {
  const standing = useQuery(partyOpening(clientId, partyId))
  const save = useBreakDownOpening(clientId, partyId)
  const [rows, setRows] = useState<Row[]>([blank()])

  const parsed = rows.map((r) => ({ reference: r.reference.trim(), date: parseDate(r.date), paise: parseRupees(r.amount) }))
  const complete = parsed.filter((r) => r.reference && r.date && r.paise && r.paise > 0)
  const entered = complete.reduce((sum, r) => sum + (r.paise ?? 0), 0)
  const remaining = standing.data?.remaining_paise ?? 0
  const problem =
    complete.length !== rows.length
      ? 'Each row needs an invoice number, a date (DD-MM-YYYY) and an amount.'
      : entered > remaining
        ? `These add up to ${formatPaise(entered)}, more than the ${formatPaise(remaining)} that is left.`
        : null

  function update(i: number, patch: Partial<Row>) {
    setRows(rows.map((r, at) => (at === i ? { ...r, ...patch } : r)))
  }

  function submit() {
    if (problem) return
    save.mutate(
      complete.map((r) => ({ reference: r.reference, bill_date: r.date as string, amount_paise: r.paise as number })),
      {
        onSuccess: () => {
          toast.success('Opening balance broken into bills')
          onClose()
        },
        onError: (e) => toast.error(messageOf(e)),
      },
    )
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[92svh] overflow-y-auto sm:max-w-2xl" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{partyName}: opening balance</DialogTitle>
          <DialogDescription>
            List the invoices the imported balance is made of. Nothing is posted: the balance is already in the ledger, this says what it is made of.
          </DialogDescription>
        </DialogHeader>

        {standing.isPending ? (
          <Spinner label="Reading the opening balance…" />
        ) : standing.isError ? (
          <ErrorState error={standing.error} retry={() => void standing.refetch()} />
        ) : !standing.data.direction ? (
          <p className="text-sm text-muted-foreground">{partyName} has no opening balance.</p>
        ) : (
          <>
            <p className="text-sm">
              {standing.data.direction === 'CR' ? 'The client owes' : 'Owed to the client'}{' '}
              <Money display={standing.data.opening_display} /> at the start of FY {standing.data.financial_year}.{' '}
              <strong className="tabular-nums">{standing.data.remaining_display}</strong> is not yet broken into bills.
            </p>
            <div className="grid gap-2">
              {rows.map((row, i) => (
                <div key={i} className="grid grid-cols-[1fr_9rem_9rem_auto] items-start gap-2 max-sm:grid-cols-1">
                  <Input
                    aria-label={`Invoice number ${i + 1}`}
                    placeholder="Invoice no."
                    value={row.reference}
                    maxLength={64}
                    onChange={(e) => update(i, { reference: e.target.value })}
                  />
                  <DateInput aria-label={`Invoice date ${i + 1}`} value={row.date} onChange={(e) => update(i, { date: e.target.value })} />
                  <Input
                    aria-label={`Amount ${i + 1}`}
                    inputMode="decimal"
                    className="text-right tabular-nums"
                    placeholder="Amount ₹"
                    value={row.amount}
                    onChange={(e) => update(i, { amount: e.target.value })}
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Remove row ${i + 1}`}
                    disabled={rows.length === 1}
                    onClick={() => setRows(rows.filter((_, at) => at !== i))}
                  >
                    <Trash2 />
                  </Button>
                </div>
              ))}
              <div>
                <Button variant="outline" size="sm" onClick={() => setRows([...rows, blank()])}>
                  <Plus /> Add an invoice
                </Button>
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span>
                Listed <strong className="tabular-nums">{formatPaise(entered)}</strong> of{' '}
                <span className="tabular-nums">{formatPaise(remaining)}</span> left
              </span>
              <Button onClick={submit} disabled={save.isPending || !!problem}>
                {save.isPending ? 'Saving…' : 'Save bills'}
              </Button>
            </div>
            {problem && rows.some((r) => r.reference || r.date || r.amount) && (
              <p role="alert" className="text-sm text-destructive">{problem}</p>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
