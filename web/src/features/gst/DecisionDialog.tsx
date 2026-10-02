// One invoice, both sides, and what the person decides about it.
//
// Opens from a row (click or its Decide button). It shows the books' figures next to GSTR-2B's, why
// the row is in its group, what to do, and, for someone who may decide, only the decisions the
// server will accept on this kind of row. A note is not a decision and is said to be one only in
// the confirmation. On a signed run, or for a reader, it is the same view without the form.

import { useState } from 'react'
import { toast } from 'sonner'
import { messageOf } from '@/api/errors'
import type { GstGroup, GstInvoice, GstRow } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/controls'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Money } from '@/components/ca/Money'
import { formatDate, formatDateTime } from '@/lib/format'
import {
  allowedDecisions,
  DECISION_BADGE,
  DECISION_HINT,
  DECISION_LABEL,
  differenceOf,
  differenceWords,
  invoiceOf,
  isCreditNote,
  ITC_LABEL,
  needsDecision,
} from './logic'
import type { GstDecisionKind } from '@/api/types'

const HEADS = [
  ['taxable_paise', 'Taxable value'],
  ['igst_paise', 'IGST'],
  ['cgst_paise', 'CGST'],
  ['sgst_paise', 'SGST'],
  ['cess_paise', 'Cess'],
] as const

type Head = (typeof HEADS)[number][0]

const figure = (inv: GstInvoice | null, head: Head) => (inv ? <Money paise={inv[head]} symbol={false} /> : <span className="text-faint">–</span>)

export function DecisionDialog({
  group,
  row,
  canDecide,
  busy,
  onDecide,
  onClose,
}: {
  group: GstGroup
  row: GstRow
  /** The person holds gst.prepare and the run is still a draft. */
  canDecide: boolean
  busy: boolean
  /** Rejects with the server's error; the dialog shows it and stays open. */
  onDecide: (kind: GstDecisionKind, note: string) => Promise<unknown>
  onClose: () => void
}) {
  const ref = invoiceOf(row)
  const options = allowedDecisions(group.kind)
  const [kind, setKind] = useState<GstDecisionKind | ''>(row.decision && options.includes(row.decision.kind) ? row.decision.kind : '')
  const [note, setNote] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  const [fieldError, setFieldError] = useState<{ kind?: string; note?: string }>({})
  const diff = differenceOf(row)

  async function save() {
    if (!kind) return setFieldError({ kind: 'Choose what to do with this invoice.' })
    if (kind === 'note' && !note.trim()) return setFieldError({ note: 'Write the note.' })
    setFieldError({})
    setProblem(null)
    try {
      await onDecide(kind, note.trim())
      toast.success(kind === 'note' ? 'Note saved. No decision was recorded.' : `Saved: ${DECISION_BADGE[kind]}`)
      onClose()
    } catch (e) {
      setProblem(messageOf(e))
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent className="max-w-3xl" aria-describedby="decision-group">
        <DialogHeader>
          <DialogTitle>
            {ref.supplier_name || 'Unnamed supplier'} <span className="font-normal text-muted-foreground">· {ref.invoice_no}</span>
          </DialogTitle>
          <DialogDescription id="decision-group">
            {group.title}
            {ref.invoice_date ? ` · invoice dated ${formatDate(ref.invoice_date)}` : ''}
            {ref.gstin ? ` · ${ref.gstin}` : ' · no GSTIN on the invoice'}
          </DialogDescription>
        </DialogHeader>

        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Figures in the books and in GSTR-2B for this invoice, in rupees</caption>
            <thead className="border-b bg-surface-2 text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-3 py-2 font-semibold">
                  <span className="sr-only">Figure</span>
                </th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Books ₹</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">GSTR-2B ₹</th>
                <th scope="col" className="px-3 py-2 text-right font-semibold">Difference ₹</th>
              </tr>
            </thead>
            <tbody>
              {HEADS.map(([head, label]) => {
                const d = (row.differences ?? {})[head] ?? 0
                return (
                  <tr key={head} className="border-b last:border-b-0">
                    <th scope="row" className="px-3 py-1.5 font-normal text-muted-foreground">{label}</th>
                    <td className="num px-3 py-1.5 text-right">{figure(row.book, head)}</td>
                    <td className="num px-3 py-1.5 text-right">{figure(row.portal, head)}</td>
                    <td className="num px-3 py-1.5 text-right">
                      {d === 0 ? (
                        <span className="text-faint">–</span>
                      ) : (
                        <span title={differenceWords(d) ?? undefined}>
                          <Money paise={Math.abs(d)} symbol={false} /> <span className="text-xs text-muted-foreground">{d > 0 ? 'books higher' : 'books lower'}</span>
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[auto_1fr]">
          <dt className="text-muted-foreground">Credit</dt>
          <dd>
            {ITC_LABEL[row.itc_status]}: eligible <Money paise={row.eligible_paise} />
            {row.ineligible_paise !== 0 && (
              <>
                , not claimable <Money paise={row.ineligible_paise} />
              </>
            )}
            {isCreditNote(row) && <Badge tone="neutral" className="ml-2">Credit note, reduces credit</Badge>}
          </dd>
          {row.cause && (
            <>
              <dt className="text-muted-foreground">Why it is here</dt>
              <dd>{row.cause}</dd>
            </>
          )}
          {row.action && (
            <>
              <dt className="text-muted-foreground">What to do</dt>
              <dd>{row.action}</dd>
            </>
          )}
          {row.timing && (
            <>
              <dt className="text-muted-foreground">Timing</dt>
              <dd>A difference of month, not an error: it may clear when the supplier files.</dd>
            </>
          )}
          {(diff.taxable !== 0 || diff.tax !== 0) && (
            <>
              <dt className="text-muted-foreground">Books minus GSTR-2B</dt>
              <dd>{[differenceWords(diff.taxable) && `Taxable: ${differenceWords(diff.taxable)}`, differenceWords(diff.tax) && `Tax: ${differenceWords(diff.tax)}`].filter(Boolean).join('. ')}</dd>
            </>
          )}
          <dt className="text-muted-foreground">Decision so far</dt>
          <dd>
            {row.decision ? (
              <>
                <Badge tone="done">{DECISION_BADGE[row.decision.kind]}</Badge>{' '}
                <span className="num text-muted-foreground">{formatDateTime(row.decision.at)}</span>
                {row.decision.note && <div className="mt-1">“{row.decision.note}”</div>}
              </>
            ) : needsDecision(group.kind, row) ? (
              <Badge tone="attention">Needs a decision</Badge>
            ) : (
              <span className="text-muted-foreground">None needed</span>
            )}
          </dd>
        </dl>

        {canDecide ? (
          <form
            className="grid gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              void save()
            }}
            noValidate
          >
            <fieldset className="grid gap-1.5" aria-describedby={fieldError.kind ? 'decision-kind-error' : undefined}>
              <legend className="mb-1 text-[13px] font-medium text-heading">What do you want to do?</legend>
              {options.map((option) => (
                <label key={option} className="flex cursor-pointer items-start gap-2.5 rounded-md border p-2.5 text-sm has-[:checked]:border-primary has-[:checked]:bg-accent">
                  <input
                    type="radio"
                    name="decision"
                    value={option}
                    checked={kind === option}
                    onChange={() => {
                      setKind(option)
                      setFieldError({})
                    }}
                    className="mt-0.5 size-4 accent-[var(--primary)]"
                  />
                  <span>
                    <span className="font-medium">{DECISION_LABEL[option]}</span>
                    <span className="block text-[13px] text-muted-foreground">{DECISION_HINT[option]}</span>
                  </span>
                </label>
              ))}
              {fieldError.kind && (
                <p id="decision-kind-error" role="alert" className="text-[13px] text-destructive">
                  {fieldError.kind}
                </p>
              )}
            </fieldset>
            <Field label={kind === 'note' ? 'Note' : 'Note (optional)'} error={fieldError.note} hint="Kept with this invoice and shown to whoever signs the run off.">
              {(props) => <Textarea {...props} value={note} onChange={(e) => setNote(e.target.value)} maxLength={2000} />}
            </Field>
            {problem && (
              <p role="alert" className="text-sm text-destructive">
                {problem}
              </p>
            )}
            <DialogFooter>
              <Button variant="ghost" onClick={onClose} disabled={busy}>
                Cancel
              </Button>
              <Button type="submit" loading={busy}>
                {kind === 'note' ? 'Save note' : 'Save decision'}
              </Button>
            </DialogFooter>
          </form>
        ) : (
          <DialogFooter>
            <Button variant="secondary" onClick={onClose}>
              Close
            </Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  )
}
