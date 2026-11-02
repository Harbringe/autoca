// A month's PF and ESI working, from the booked salary run, and where each employee's UAN and ESIC number are kept.

import { useQuery } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { useState } from 'react'
import { messageOf } from '@/api/errors'
import { pfEsi, useSetEmployeeNumbers } from '@/api/queries/bills'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { formatDate, formatPaise } from '@/lib/format'
import { toast } from '@/lib/toast'

const money = (paise: number) => (paise === 0 ? '–' : formatPaise(paise, { symbol: false }))
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

type Person = { id: string; name: string; uan?: string; esic_number?: string }

function Numbers({ clientId, person, mayEdit }: { clientId: string; person: Person; mayEdit: boolean }) {
  const save = useSetEmployeeNumbers(clientId)
  const [uan, setUan] = useState(person.uan ?? '')
  const [esic, setEsic] = useState(person.esic_number ?? '')
  const changed = uan !== (person.uan ?? '') || esic !== (person.esic_number ?? '')
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="w-40">{person.name}</span>
      <Input aria-label={`UAN of ${person.name}`} className="w-40" placeholder="UAN (12 digits)" value={uan} disabled={!mayEdit} onChange={(e) => setUan(e.target.value)} />
      <Input aria-label={`ESIC number of ${person.name}`} className="w-44" placeholder="ESIC number" value={esic} disabled={!mayEdit} onChange={(e) => setEsic(e.target.value)} />
      {mayEdit && (
        <Button
          size="sm"
          variant="outline"
          disabled={!changed || save.isPending}
          onClick={() => save.mutate({ id: person.id, uan, esic_number: esic }, { onSuccess: () => toast.success('Saved'), onError: (e) => toast.error(messageOf(e)) })}
        >
          Save
        </Button>
      )}
    </div>
  )
}

export function PfEsiWorking({ clientId, mayEdit, people }: { clientId: string; mayEdit: boolean; people: Person[] }) {
  const today = new Date()
  const [year, setYear] = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth() === 0 ? 12 : today.getMonth())
  const query = useQuery(pfEsi(clientId, year, month))
  const d = query.data

  return (
    <section className="grid gap-3 text-sm" aria-label="PF and ESI working">
      <h2 className="text-[15px] font-semibold text-heading">PF and ESI working</h2>
      <div className="grid gap-1">
        <p className="text-muted-foreground">The returns name each person by their UAN (PF) and ESIC number.</p>
        {people.map((p) => (
          <Numbers key={`${p.id}-${p.uan}-${p.esic_number}`} clientId={clientId} person={p} mayEdit={mayEdit} />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="pfesi-month" className="text-muted-foreground">
          PF and ESI month
        </label>
        <select id="pfesi-month" className="h-9 rounded-md border border-border-strong bg-transparent px-2" value={month} onChange={(e) => setMonth(Number(e.target.value))}>
          {MONTHS.map((m, i) => (
            <option key={m} value={i + 1}>
              {m}
            </option>
          ))}
        </select>
        <Input aria-label="PF and ESI year" className="w-24" inputMode="numeric" value={year} onChange={(e) => setYear(Number(e.target.value) || year)} />
      </div>
      {d && !d.has_run && <p className="text-muted-foreground">No salary run is booked for this month.</p>}
      {d?.has_run && d.rows && d.totals && (
        <>
          {(d.warnings ?? []).length > 0 && (
            <ul className="grid gap-1">
              {d.warnings!.map((w) => (
                <li key={w} className="flex gap-2">
                  <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                  {w}
                </li>
              ))}
            </ul>
          )}
          <table className="w-full" aria-label="PF and ESI by employee">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="py-1 font-medium">Employee</th>
                <th className="py-1 text-right font-medium">PF wages</th>
                <th className="py-1 text-right font-medium">Employee PF</th>
                <th className="py-1 text-right font-medium">Pension (EPS)</th>
                <th className="py-1 text-right font-medium">Employer PF (EPF)</th>
                <th className="py-1 text-right font-medium">Gross</th>
                <th className="py-1 text-right font-medium">Employee ESI</th>
                <th className="py-1 text-right font-medium">Employer ESI</th>
              </tr>
            </thead>
            <tbody>
              {d.rows.map((r) => (
                <tr key={r.employee} className="border-t border-border-strong">
                  <td className="py-1">{r.employee}</td>
                  <td className="py-1 text-right tabular-nums">{money(r.pf_wages_paise)}</td>
                  <td className="py-1 text-right tabular-nums">{money(r.pf_employee_paise)}</td>
                  <td className="py-1 text-right tabular-nums">{money(r.eps_paise)}</td>
                  <td className="py-1 text-right tabular-nums">{money(r.epf_paise)}</td>
                  <td className="py-1 text-right tabular-nums">{money(r.gross_paise)}</td>
                  <td className="py-1 text-right tabular-nums">{money(r.esi_employee_paise)}</td>
                  <td className="py-1 text-right tabular-nums">{money(r.esi_employer_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            PF to deposit {money(d.pf_total_paise ?? 0)}, plus the employer&apos;s administration charge {money(d.admin_charge_paise ?? 0)} and EDLI {money(d.edli_paise ?? 0)}. ESI to deposit{' '}
            {money(d.esi_total_paise ?? 0)}. Due by {formatDate(d.due)}. Deposited on time: PF {money(d.pf_deposit?.deposited_on_time_paise ?? 0)}, ESI{' '}
            {money(d.esi_deposit?.deposited_on_time_paise ?? 0)}; late: PF {money(d.pf_deposit?.deposited_late_paise ?? 0)}, ESI {money(d.esi_deposit?.deposited_late_paise ?? 0)}.
          </p>
          <p className="text-xs text-muted-foreground">
            PF wages are worked back from the employee&apos;s 12%. Pension is 8.33% of wages up to ₹15,000. Interest and damages on a late deposit are not worked out.
          </p>
        </>
      )}
    </section>
  )
}
