// TDS: what the client deducted, what it has paid in, and what is late.
//
// Read from the books: a purchase that deducts TDS credits TDS Payable with its section, and a bank payment to the tax
// department debits it. Deposits are matched to the oldest deduction of their section first. A deposit needs its challan
// (the section, BSR code and serial number) recorded before the quarterly return can use it.

import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { tdsSummary, useRecordChallan } from '@/api/queries/bills'
import { clientDetail, V1 } from '@/api/queries/clients'
import { Money } from '@/components/ca/Money'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DateInput } from '@/components/ui/date-input'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { ColumnChart, ColumnSkeleton, EmptyPlot } from '@/components/charts/ColumnChart'
import { GlideChips } from '@/components/ui/glide-chips'
import { tdsByMonth } from '@/lib/reportSeries'
import { Spinner } from '@/components/ui/spinner'
import { formatDate, fyLabel, parseDate } from '@/lib/format'
import { saveFile } from '@/platform/download'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function currentFy() {
  const now = new Date()
  return now.getMonth() >= 3 ? now.getFullYear() : now.getFullYear() - 1
}

/** The quarter's Form 26Q data: deductees, challans, and what is late or missing, with the Excel to file from. */
function ReturnData({ clientId }: { clientId: string }) {
  const [fy, setFy] = useState(currentFy())
  const [quarter, setQuarter] = useState(1)
  const [form, setForm] = useState<'return' | 'salary-return'>('return')
  const pack = useQuery({
    queryKey: ['tds-return', clientId, form, fy, quarter],
    queryFn: () =>
      raw.get<{
        due: string; deducted_paise: number; deposited_paise: number; interest_paise: number; fee_paise: number
        warnings: string[]; deductees?: unknown[]; employees?: unknown[]; challans: unknown[]
      }>(`${V1}/clients/${clientId}/tds/${form}/`, { fy, quarter }),
    placeholderData: keepPreviousData,
  })
  // Remounts (and so fades in) only when a new quarter has really arrived, not while the old one is held, dimmed, in its place.
  const arrived = useRef(0)
  if (pack.data && !pack.isPlaceholderData) arrived.current = pack.dataUpdatedAt
  const [downloading, setDownloading] = useState(false)
  async function download() {
    setDownloading(true)
    try {
      const { blob, filename } = await raw.blob(`${V1}/clients/${clientId}/tds/${form}/export/`, { fy, quarter })
      await saveFile(filename ?? `tds-${form === 'return' ? '26Q' : '24Q'}-FY${fy}-Q${quarter}.xlsx`, blob)
    } catch (e) {
      toast.error(messageOf(e))
    } finally {
      setDownloading(false)
    }
  }
  const rupees = (paise: number) => `₹${(paise / 100).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`
  return (
    <section className="grid gap-2" aria-labelledby="tds-return">
      <h2 id="tds-return" className="text-[15px] font-semibold text-heading">Quarterly return data (Form 26Q and 24Q)</h2>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <GlideChips
          label="Return"
          value={form}
          onChange={setForm}
          options={[
            { value: 'return', label: '26Q (other than salary)' },
            { value: 'salary-return', label: '24Q (salary)' },
          ]}
        />
        <label className="flex items-center gap-1.5">
          Financial year
          <select className="h-9 rounded-md border bg-background px-2" value={fy} onChange={(e) => setFy(Number(e.target.value))}>
            {[currentFy(), currentFy() - 1, currentFy() - 2].map((y) => <option key={y} value={y}>{fyLabel(y)}</option>)}
          </select>
        </label>
        <GlideChips
          label="Quarter"
          value={`Q${quarter}`}
          onChange={(q) => setQuarter(Number(q.slice(1)))}
          options={[1, 2, 3, 4].map((q) => ({ value: `Q${q}`, label: `Q${q}` }))}
        />
        <Button variant="outline" onClick={() => void download()} loading={downloading} disabled={!pack.data}>Download Excel</Button>
      </div>
      {pack.isPending ? (
        <Spinner label="Reading the quarter…" />
      ) : pack.isError ? (
        <ErrorState error={pack.error} retry={() => void pack.refetch()} />
      ) : (
        <div key={arrived.current} aria-busy={pack.isPlaceholderData || undefined} className={cn('fade-in grid gap-2 rounded-lg border bg-card p-3 text-sm transition-opacity duration-200', pack.isPlaceholderData && 'opacity-50')}>
          <p>
            {(pack.data.deductees ?? pack.data.employees ?? []).length} {form === 'return' ? 'deduction' : 'employee'}{(pack.data.deductees ?? pack.data.employees ?? []).length === 1 ? '' : 's'}, {rupees(pack.data.deducted_paise)} deducted,{' '}
            {rupees(pack.data.deposited_paise)} deposited. Return due {formatDate(pack.data.due)}.
          </p>
          {pack.data.interest_paise + pack.data.fee_paise > 0 && (
            <p className="text-warning">
              At stake (estimate): interest {rupees(pack.data.interest_paise)}, late fee {rupees(pack.data.fee_paise)}.
            </p>
          )}
          {pack.data.warnings.length > 0 && (
            <ul className="grid list-disc gap-1 pl-5">
              {pack.data.warnings.map((w) => <li key={w}>{w}</li>)}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}

export function TdsScreen({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const summary = useQuery(tdsSummary(clientId))
  const [recording, setRecording] = useState<string | null>(null)
  const mayRecord = can('journal.approve') && !!client.data?.can_post

  if (summary.isPending) {
    return (
      <div aria-busy="true" className="grid gap-3">
        <span className="sr-only">Working out the TDS position…</span>
        <ColumnSkeleton />
      </div>
    )
  }
  if (summary.isError) return <ErrorState error={summary.error} retry={() => void summary.refetch()} />
  const { months, payments_without_challan: loose } = summary.data

  if (months.length === 0 && loose.length === 0) {
    return (
      <EmptyState title="No TDS yet">
        <EmptyPlot line="Deducted and deposited TDS is drawn here by month." className="mx-auto mb-3 max-w-sm text-left" />
        When a purchase deducts TDS it is credited to TDS Payable with its section, and it appears here with the date it is due.
      </EmptyState>
    )
  }

  return (
    <div className="grid gap-4">
      <ReturnData clientId={clientId} />
      {loose.length > 0 && (
        <section className="grid gap-2" aria-labelledby="tds-loose">
          <h2 id="tds-loose" className="text-[15px] font-semibold text-heading">Payments to the tax department with no challan</h2>
          <ul className="grid gap-2">
            {loose.map((p, i) => (
              <li key={p.entry} className="fade-in flex flex-wrap items-center justify-between gap-3 rounded-md border bg-card p-3 text-sm" style={{ animationDelay: `${Math.min(i, 8) * 50}ms` }}>
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
        {months.length > 0 && (
          <div className="no-print rounded-lg border bg-surface-2 p-4">
            <ColumnChart
              points={tdsByMonth(months).map((m) => ({
                key: m.key,
                label: MONTHS[m.month - 1]!,
                full: `${MONTHS[m.month - 1]} ${m.year}`,
                values: [m.deducted, m.deposited],
                flag: m.late ? 'Deposit overdue' : undefined,
              }))}
              series={[
                { name: 'Deducted', tone: 'out' },
                { name: 'Deposited', tone: 'good' },
              ]}
              ariaLabel="TDS deducted and deposited by month"
              caption="TDS deducted and deposited by month"
            />
          </div>
        )}
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
              {months.map((m, i) => (
                <tr key={`${m.section}-${m.year}-${m.month}`} className="fade-in border-b transition-colors last:border-0 hover:bg-hover" style={{ animationDelay: `${Math.min(i, 10) * 40}ms` }}>
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
    <Dialog open onOpenChange={(open) => !open && !record.isPending && onClose()}>
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
            <Button onClick={save} loading={record.isPending} disabled={!!problem}>{record.isPending ? 'Saving…' : 'Record'}</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
