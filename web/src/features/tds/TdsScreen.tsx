// TDS: what the client deducted, what it has paid in, and what is late.
//
// Read from the books: a purchase that deducts TDS credits TDS Payable with its section, and a bank payment to the tax
// department debits it. Deposits are matched to the oldest deduction of their section first. A deposit needs its challan
// (the section, BSR code and serial number) recorded before the quarterly return can use it.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'
import { messageOf } from '@/api/errors'
import { tdsSummary, useRecordChallan } from '@/api/queries/bills'
import { clientDetail } from '@/api/queries/clients'
import { Money } from '@/components/ca/Money'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DateInput } from '@/components/ui/date-input'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, fyLabel, parseDate } from '@/lib/format'
import { useSession } from '@/session/session'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function TdsScreen({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const summary = useQuery(tdsSummary(clientId))
  const [recording, setRecording] = useState<string | null>(null)
  const mayRecord = can('journal.approve') && !!client.data?.can_post

  if (summary.isPending) return <Spinner label="Working out the TDS position…" />
  if (summary.isError) return <ErrorState error={summary.error} retry={() => void summary.refetch()} />
  const { months, payments_without_challan: loose } = summary.data

  if (months.length === 0 && loose.length === 0) {
    return (
      <EmptyState title="No TDS yet">
        When a purchase deducts TDS it is credited to TDS Payable with its section, and it appears here with the date it is due.
      </EmptyState>
    )
  }

  return (
    <div className="grid gap-4">
      {loose.length > 0 && (
        <section className="grid gap-2" aria-labelledby="tds-loose">
          <h2 id="tds-loose" className="text-[15px] font-semibold text-heading">Payments to the tax department with no challan</h2>
          <ul className="grid gap-2">
            {loose.map((p) => (
              <li key={p.entry} className="flex flex-wrap items-center justify-between gap-3 rounded-md border bg-card p-3 text-sm">
                <span>
                  <Money display={p.amount_display} /> paid on {formatDate(p.entry_date)}
                </span>
                {mayRecord && <Button size="sm" onClick={() => setRecording(p.entry)}>Record the challan</Button>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="grid gap-2" aria-labelledby="tds-months">
        <h2 id="tds-months" className="text-[15px] font-semibold text-heading">Deducted and deposited, by section and month</h2>
        <div className="overflow-x-auto rounded-lg border bg-card">
          <table className="w-full min-w-[44rem] text-sm">
            <caption className="sr-only">TDS by section and month</caption>
            <thead className="border-b text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="p-2 text-left font-medium">Section</th>
                <th scope="col" className="p-2 text-left font-medium">Month</th>
                <th scope="col" className="p-2 text-right font-medium">Deducted (₹)</th>
                <th scope="col" className="p-2 text-right font-medium">Deposited (₹)</th>
                <th scope="col" className="p-2 text-right font-medium">Unpaid (₹)</th>
                <th scope="col" className="p-2 text-left font-medium">Due</th>
              </tr>
            </thead>
            <tbody>
              {months.map((m) => (
                <tr key={`${m.section}-${m.year}-${m.month}`} className="border-b last:border-0">
                  <th scope="row" className="p-2 text-left font-medium">{m.section === '?' ? 'Not stated' : m.section}</th>
                  <td className="p-2">
                    {MONTHS[m.month - 1]} {m.year} <span className="text-xs text-muted-foreground">Q{m.quarter} FY {fyLabel(m.financial_year)}</span>
                  </td>
                  <td className="p-2 text-right"><Money display={m.deducted_display} symbol={false} /></td>
                  <td className="p-2 text-right"><Money display={m.deposited_display} symbol={false} /></td>
                  <td className="p-2 text-right"><Money display={m.unpaid_display} symbol={false} muted={m.unpaid_paise === 0} /></td>
                  <td className="p-2">
                    {formatDate(m.due)} {m.overdue && <Badge tone="danger">Late</Badge>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {recording && <ChallanDialog clientId={clientId} entry={recording} onClose={() => setRecording(null)} />}
    </div>
  )
}

function ChallanDialog({ clientId, entry, onClose }: { clientId: string; entry: string; onClose: () => void }) {
  const record = useRecordChallan(clientId)
  const [section, setSection] = useState('')
  const [bsr, setBsr] = useState('')
  const [serial, setSerial] = useState('')
  const [paidOn, setPaidOn] = useState('')
  const date = parseDate(paidOn)
  const problem = !section.trim()
    ? 'Say which section it was for.'
    : !/^\d{7}$/.test(bsr)
      ? 'The BSR code is seven digits.'
      : !/^\d{5}$/.test(serial)
        ? 'The challan serial is five digits.'
        : !date
          ? 'Enter the date as DD-MM-YYYY.'
          : null

  function save() {
    if (problem || !date) return
    record.mutate(
      { entry, section: section.trim().toUpperCase(), bsr_code: bsr, serial, paid_on: date },
      {
        onSuccess: () => {
          toast.success('Challan recorded')
          onClose()
        },
        onError: (e) => toast.error(messageOf(e)),
      },
    )
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-md" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Record the challan</DialogTitle>
          <DialogDescription>From the challan the bank gave you for this payment to the tax department.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <Field label="Section">{(p) => <Input {...p} placeholder="194C" value={section} onChange={(e) => setSection(e.target.value)} />}</Field>
          <Field label="BSR code (7 digits)">{(p) => <Input {...p} inputMode="numeric" maxLength={7} value={bsr} onChange={(e) => setBsr(e.target.value)} />}</Field>
          <Field label="Challan serial (5 digits)">{(p) => <Input {...p} inputMode="numeric" maxLength={5} value={serial} onChange={(e) => setSerial(e.target.value)} />}</Field>
          <Field label="Date paid">{(p) => <DateInput {...p} value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />}</Field>
          {problem && paidOn && <p role="alert" className="text-sm text-destructive">{problem}</p>}
          <div className="flex justify-end">
            <Button onClick={save} disabled={!!problem || record.isPending}>{record.isPending ? 'Saving…' : 'Record'}</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
