// The part of settling a payment that is the same wherever it happens: the party's open bills with an amount against each,
// prefilled from the server's suggestion and editable, what is left held on account or as an advance, and the totals worked
// out as it is edited. Used for a row waiting in the review queue, and for a payment already posted that was never settled.
//
// It only gathers a person's decision. The server re-checks all of it and is the authority.

import { useEffect, useMemo, useState } from 'react'
import type { SettlementContext } from '@/api/types'
import { Money } from '@/components/ca/Money'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/controls'
import { Input } from '@/components/ui/input'
import { formatDate, formatPaise } from '@/lib/format'
import { basisNote, decide, draftFrom, HOLD_LABEL, type Decision, type Draft, type Hold } from '@/lib/settlement'

export function SettlementEditor({
  context,
  busy,
  confirmLabel,
  onSubmit,
}: {
  context: SettlementContext
  busy: boolean
  confirmLabel: string
  onSubmit: (decision: Decision) => void
}) {
  const [draft, setDraft] = useState<Draft>(() => draftFrom(context.proposal))
  // A different payment (or a refreshed suggestion) starts again from its own suggestion.
  useEffect(() => setDraft(draftFrom(context.proposal)), [context])

  const bills = context.bills
  const decision = useMemo(
    () => decide(context.amount_paise, bills.map((b) => ({ id: b.id, reference: b.reference, open_paise: b.open_paise })), draft),
    [context.amount_paise, bills, draft],
  )
  const paying = context.direction === 'DR'
  const suggested = context.proposal.allocations.map((a) => bills.find((b) => b.id === a.bill)?.reference ?? '')

  return (
    <section aria-label={`Settle ${context.party.name}’s bills`} className="grid gap-3 rounded-md border border-accent-edge bg-accent p-3">
      <div>
        <h3 className="text-[13px] font-semibold">On {context.party.name}’s account</h3>
        <p className="text-sm">
          {paying ? 'Paid' : 'Received'} <Money display={context.amount_display} />. Say which bills it settles; nothing is posted until you do.
        </p>
        <p className="mt-1 text-xs text-muted-foreground">Suggested: {basisNote(context.proposal.basis, suggested)} You can change any amount.</p>
      </div>

      {bills.length > 0 ? (
        <table className="w-full text-sm">
          <caption className="sr-only">Open bills of {context.party.name}</caption>
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
        <p className="text-sm text-muted-foreground">{context.party.name} has no open bills on this side, so all of it will be held.</p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span>
          Settles <strong className="tabular-nums">{formatPaise(decision.allocated)}</strong> of{' '}
          <span className="tabular-nums">{formatPaise(context.amount_paise)}</span>
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
        <Button onClick={() => onSubmit(decision)} disabled={busy || !!decision.problem}>
          {busy ? 'Posting…' : confirmLabel}
        </Button>
      </div>
    </section>
  )
}
