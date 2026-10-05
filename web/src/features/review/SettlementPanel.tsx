// A payment on a supplier's or customer's own account: which of their bills does it pay?
//
// The bank row says money moved to or from this party and nothing about which invoices it clears, so nothing is posted until
// a person says. The panel lists the party's open bills with an amount against each, prefilled from the server's suggestion
// (a bill that is exactly this amount; a small set that adds up to it; otherwise the oldest first), and whatever the bills do
// not take is held on account or as an advance. The suggestion is only that: the person confirms every amount, and the server
// re-checks it all.

import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { rowSettlement } from '@/api/queries/bills'
import { useInvalidateClient, V1 } from '@/api/queries/clients'
import type { Classification } from '@/api/types'
import { Money } from '@/components/ca/Money'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/controls'
import { Input } from '@/components/ui/input'
import { formatDate, formatPaise } from '@/lib/format'
import { basisNote, decide, draftFrom, HOLD_LABEL, type Draft, type Hold } from '@/lib/settlement'

export function SettlementPanel({ clientId, row, onDone }: { clientId: string; row: Classification; onDone: () => void }) {
  const context = useQuery(rowSettlement(clientId, row.id))
  const invalidate = useInvalidateClient(clientId)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [busy, setBusy] = useState(false)

  // Start from the server's suggestion, once, when it arrives. Whatever the person types after that is theirs.
  useEffect(() => {
    if (context.data && !draft) setDraft(draftFrom(context.data.proposal))
  }, [context.data, draft])

  const bills = context.data?.bills ?? []
  const decision = useMemo(
    () =>
      context.data && draft
        ? decide(context.data.amount_paise, bills.map((b) => ({ id: b.id, reference: b.reference, open_paise: b.open_paise })), draft)
        : null,
    [context.data, draft, bills],
  )

  if (context.isPending) return <p className="text-sm text-muted-foreground">Looking up {row.party_name ?? 'the party'}’s open bills…</p>
  if (context.isError) return <p role="alert" className="text-sm text-destructive">{messageOf(context.error)}</p>
  if (!context.data || !draft || !decision) return null

  const ctx = context.data
  const paying = ctx.direction === 'DR'
  const suggested = ctx.proposal.allocations.map((a) => bills.find((b) => b.id === a.bill)?.reference ?? '')

  async function postAndSettle() {
    if (!decision || decision.problem) return
    setBusy(true)
    try {
      await raw.post(`${V1}/clients/${clientId}/approvals/`, {
        classifications: [row.id],
        settlements: [{ classification: row.id, allocations: decision.allocations, remainder: decision.remainder }],
      })
      await invalidate()
      toast.success('Posted, and the bills are settled')
      onDone()
    } catch (e) {
      toast.error(messageOf(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-label={`Settle ${ctx.party.name}’s bills`} className="grid gap-3 rounded-md border border-accent-edge bg-accent p-3">
      <div>
        <h3 className="text-[13px] font-semibold">On {ctx.party.name}’s account</h3>
        <p className="text-sm">
          {paying ? 'Paid' : 'Received'} <Money display={ctx.amount_display} />. Say which bills it settles; nothing is posted until you do.
        </p>
        <p className="mt-1 text-xs text-muted-foreground">Suggested: {basisNote(ctx.proposal.basis, suggested)} You can change any amount.</p>
      </div>

      {bills.length > 0 ? (
        <table className="w-full text-sm">
          <caption className="sr-only">Open bills of {ctx.party.name}</caption>
          <thead className="text-left text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="py-1 font-medium">Invoice</th>
              <th scope="col" className="py-1 font-medium max-sm:hidden">Date</th>
              <th scope="col" className="py-1 text-right font-medium">Open (₹)</th>
              <th scope="col" className="w-36 py-1 text-right font-medium">Settle (₹)</th>
            </tr>
          </thead>
          <tbody>
            {bills.map((bill) => {
              const error = decision.fieldErrors[bill.id]
              return (
                <tr key={bill.id} className="align-top">
                  <th scope="row" className="py-1 text-left font-medium">{bill.reference}</th>
                  <td className="py-1 max-sm:hidden">{formatDate(bill.bill_date)}</td>
                  <td className="py-1 text-right"><Money display={bill.open_display} symbol={false} /></td>
                  <td className="py-1">
                    <Input
                      aria-label={`Settle against ${bill.reference}`}
                      aria-invalid={!!error}
                      inputMode="decimal"
                      className="h-8 text-right tabular-nums"
                      value={draft.amounts[bill.id] ?? ''}
                      onChange={(e) => setDraft({ ...draft, amounts: { ...draft.amounts, [bill.id]: e.target.value } })}
                    />
                    {error && <p role="alert" className="mt-0.5 text-xs text-destructive">{error}</p>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      ) : (
        <p className="text-sm text-muted-foreground">{ctx.party.name} has no open bills on this side, so all of it will be held.</p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span>
          Settles <strong className="tabular-nums">{formatPaise(decision.allocated)}</strong> of{' '}
          <span className="tabular-nums">{formatPaise(ctx.amount_paise)}</span>
          {decision.left > 0 && <> · <strong className="tabular-nums">{formatPaise(decision.left)}</strong> left over</>}
        </span>
        {decision.left > 0 && (
          <label className="flex items-center gap-2">
            <span className="text-muted-foreground">Hold the rest as</span>
            <Select
              aria-label="What to do with the rest"
              className="w-72"
              value={draft.remainder}
              onChange={(e) => setDraft({ ...draft, remainder: e.target.value as Hold })}
            >
              {(Object.keys(HOLD_LABEL) as Hold[]).map((kind) => (
                <option key={kind} value={kind}>{HOLD_LABEL[kind]}</option>
              ))}
            </Select>
          </label>
        )}
      </div>

      {decision.problem && <p role="alert" className="text-sm text-destructive">{decision.problem}</p>}

      <div className="flex justify-end">
        <Button onClick={() => void postAndSettle()} disabled={busy || !!decision.problem}>
          {busy ? 'Posting…' : 'Post and settle'}
        </Button>
      </div>
    </section>
  )
}
