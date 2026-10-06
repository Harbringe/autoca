// Payroll: the people the client pays, and a month of salaries booked as one entry.
//
// The figures are typed from the salary sheet; the books record them, they do not work out PF or ESI. A run credits each
// employee's own account with their net pay, and PF, ESI and tax deducted on salary to their payable accounts, so the bank
// payments that follow are placed against those. Tax on salary shows on the TDS page under section 192.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'
import { messageOf } from '@/api/errors'
import { employees, payrollRuns, useAddEmployee, useBookSalaries, useRemoveSalaries, type SalaryLine } from '@/api/queries/bills'
import { clientDetail } from '@/api/queries/clients'
import { Money } from '@/components/ca/Money'
import { EmptyState, ErrorState } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/controls'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { formatPaise, parseRupees, plural } from '@/lib/format'
import { useSession } from '@/session/session'

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
const FIELDS = [
  ['gross', 'Gross'],
  ['pfEmployee', 'PF (employee)'],
  ['pfEmployer', 'PF (employer)'],
  ['esiEmployee', 'ESI (employee)'],
  ['esiEmployer', 'ESI (employer)'],
  ['tds', 'TDS'],
  ['other', 'Other deduction'],
] as const
type Field = (typeof FIELDS)[number][0]
type Row = Record<Field, string>

const blank = (): Row => ({ gross: '', pfEmployee: '', pfEmployer: '', esiEmployee: '', esiEmployer: '', tds: '', other: '' })
const paise = (text: string) => (text.trim() ? parseRupees(text) : 0)

export function PayrollScreen({ clientId }: { clientId: string }) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const people = useQuery(employees(clientId))
  const runs = useQuery(payrollRuns(clientId))
  const add = useAddEmployee(clientId)
  const book = useBookSalaries(clientId)
  const remove = useRemoveSalaries(clientId)
  const today = new Date()
  const [year, setYear] = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth() === 0 ? 12 : today.getMonth())
  const [name, setName] = useState('')
  const [rows, setRows] = useState<Record<string, Row>>({})
  const mayEdit = can('journal.approve') && !!client.data?.can_post

  if (people.isPending || runs.isPending) return <Spinner label="Loading payroll…" />
  if (people.isError) return <ErrorState error={people.error} retry={() => void people.refetch()} />
  if (runs.isError) return <ErrorState error={runs.error} retry={() => void runs.refetch()} />
  const active = people.data.filter((p) => p.is_active)

  const filled = active.filter((p) => rows[p.id]?.gross?.trim())
  const lines: SalaryLine[] = []
  let problem: string | null = null
  for (const p of filled) {
    const r = rows[p.id] as Row
    const values = FIELDS.map(([key]) => paise(r[key]))
    if (values.some((v) => v === null)) {
      problem = `${p.name}: an amount is not a number. Use rupees with at most two decimals.`
      break
    }
    const [gross, pfE, pfR, esiE, esiR, tds, other] = values as number[]
    if ((gross as number) <= 0) problem = `${p.name}: the gross salary must be more than zero.`
    else if ((pfE as number) + (esiE as number) + (tds as number) + (other as number) > (gross as number)) problem = `${p.name}: the deductions are more than the gross.`
    lines.push({
      employee: p.id,
      gross_paise: gross as number,
      pf_employee_paise: pfE as number,
      pf_employer_paise: pfR as number,
      esi_employee_paise: esiE as number,
      esi_employer_paise: esiR as number,
      tds_paise: tds as number,
      other_deduction_paise: other as number,
    })
  }
  const net = lines.reduce((sum, l) => sum + l.gross_paise - l.pf_employee_paise - l.esi_employee_paise - l.tds_paise - l.other_deduction_paise, 0)

  async function addPerson() {
    try {
      await add.mutateAsync(name)
      setName('')
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  async function bookRun() {
    try {
      await book.mutateAsync({ year, month, lines })
      toast.success(`Salaries for ${MONTHS[month - 1]} ${year} booked`)
      setRows({})
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  async function takeOut(id: string) {
    try {
      await remove.mutateAsync(id)
      toast.success('Salaries taken out of the books')
    } catch (e) {
      toast.error(messageOf(e))
    }
  }

  return (
    <div className="grid gap-5">
      <section className="grid gap-2" aria-labelledby="pay-people">
        <h2 id="pay-people" className="text-[15px] font-semibold text-heading">Employees</h2>
        {mayEdit && (
          <div className="flex gap-2">
            <Input aria-label="Employee name" className="max-w-xs" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
            <Button variant="outline" onClick={() => void addPerson()} disabled={!name.trim() || add.isPending}>Add</Button>
          </div>
        )}
        {active.length === 0 ? (
          <EmptyState title="No employees yet">Add the people the client pays a salary to, then book a month.</EmptyState>
        ) : (
          <p className="text-sm text-muted-foreground">{plural(active.length, 'employee')}: {active.map((p) => p.name).join(', ')}.</p>
        )}
      </section>

      {mayEdit && active.length > 0 && (
        <section className="grid gap-2" aria-labelledby="pay-run">
          <h2 id="pay-run" className="text-[15px] font-semibold text-heading">Book a month</h2>
          <div className="flex flex-wrap items-center gap-2">
            <Select aria-label="Month" className="w-36" value={month} onChange={(e) => setMonth(Number(e.target.value))}>
              {MONTHS.map((m, i) => (
                <option key={m} value={i + 1}>{m}</option>
              ))}
            </Select>
            <Input aria-label="Year" className="w-24" inputMode="numeric" value={year} onChange={(e) => setYear(Number(e.target.value) || year)} />
          </div>
          <div className="overflow-x-auto rounded-lg border bg-card">
            <table className="w-full min-w-[56rem] text-sm">
              <caption className="sr-only">Salary sheet for {MONTHS[month - 1]} {year}</caption>
              <thead className="border-b text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="p-2 text-left font-medium">Employee</th>
                  {FIELDS.map(([key, label]) => (
                    <th key={key} scope="col" className="p-2 text-right font-medium">{label} (₹)</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {active.map((p) => (
                  <tr key={p.id} className="border-b last:border-0">
                    <th scope="row" className="p-2 text-left font-medium">{p.name}</th>
                    {FIELDS.map(([key, label]) => (
                      <td key={key} className="p-1">
                        <Input
                          aria-label={`${label} for ${p.name}`}
                          inputMode="decimal"
                          className="h-8 text-right tabular-nums"
                          value={rows[p.id]?.[key] ?? ''}
                          onChange={(e) => setRows({ ...rows, [p.id]: { ...(rows[p.id] ?? blank()), [key]: e.target.value } })}
                        />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span>
              {plural(lines.length, 'employee')} · net pay <strong className="tabular-nums">{formatPaise(net)}</strong>
            </span>
            <Button onClick={() => void bookRun()} disabled={lines.length === 0 || !!problem || book.isPending}>
              {book.isPending ? 'Booking…' : 'Book salaries'}
            </Button>
          </div>
          {problem && <p role="alert" className="text-sm text-destructive">{problem}</p>}
        </section>
      )}

      <section className="grid gap-2" aria-labelledby="pay-done">
        <h2 id="pay-done" className="text-[15px] font-semibold text-heading">Months booked</h2>
        {runs.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing booked yet.</p>
        ) : (
          <ul className="grid gap-2">
            {runs.data.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border bg-card p-3 text-sm">
                <span>{MONTHS[r.month - 1]} {r.year}</span>
                <span className="flex items-center gap-3">
                  Gross <Money display={r.gross_display} /> · Net <Money display={r.net_display} />
                  {mayEdit && <Button variant="ghost" size="sm" onClick={() => void takeOut(r.id)}>Take out</Button>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
