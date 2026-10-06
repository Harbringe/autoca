// When a statement was refused for its columns: see how its table was read, name what each column is, and try again.
//
// The reader proves every layout against the statement's own running balance, so a wrong choice here is refused with the
// row where it stops following the balance. Nothing is imported until the arithmetic agrees.

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { raw } from '@/api/client'
import { V1 } from '@/api/queries/clients'
import type { LayoutPreview } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/controls'
import { Spinner } from '@/components/ui/spinner'

const ROLES = [
  ['', 'Not used'],
  ['date', 'Date'],
  ['narration', 'Narration'],
  ['debit', 'Withdrawal (debit)'],
  ['credit', 'Deposit (credit)'],
  ['amount', 'Amount (one column)'],
  ['direction', 'Dr/Cr marker'],
  ['balance', 'Balance'],
  ['reference', 'Cheque / reference'],
] as const

/** Which role a column holds, from the roles-to-columns map the reader proposed. */
export function invertLayout(proposed: Record<string, number>): Record<number, string> {
  const byColumn: Record<number, string> = {}
  for (const [role, index] of Object.entries(proposed)) byColumn[index] = role
  return byColumn
}

/** The layout to send: only roles that were chosen, each once. Returns an error sentence when it cannot work. */
export function layoutFrom(byColumn: Record<number, string>): { layout?: Record<string, number>; problem?: string } {
  const layout: Record<string, number> = {}
  for (const [column, role] of Object.entries(byColumn)) {
    if (!role) continue
    if (role in layout) return { problem: `Two columns are marked as ${role}. Each role goes on one column.` }
    layout[role] = Number(column)
  }
  if (!('date' in layout)) return { problem: 'Mark the date column.' }
  if (!('balance' in layout)) return { problem: 'Mark the balance column.' }
  const split = 'debit' in layout && 'credit' in layout
  if (!split && !('amount' in layout)) return { problem: 'Mark the debit and credit columns, or the single amount column.' }
  return { layout }
}

export function LayoutPicker({
  clientId,
  file,
  onTry,
  onBack,
}: {
  clientId: string
  file: File
  onTry: (layout: Record<string, number>) => void
  onBack: () => void
}) {
  const preview = useQuery({
    queryKey: ['layout-preview', clientId, file.name, file.size, file.lastModified],
    queryFn: () => {
      const form = new FormData()
      form.append('file', file)
      return raw.post<LayoutPreview>(`${V1}/clients/${clientId}/statements/preview/`, form)
    },
    staleTime: Infinity,
  })
  const [chosen, setChosen] = useState<Record<number, string> | null>(null)

  if (preview.isPending) return <Spinner label="Looking at the table…" />
  if (preview.isError || !preview.data) return <p role="alert" className="text-sm text-destructive">The table could not be shown.</p>
  const data = preview.data
  if (data.rows.length === 0) return <p className="text-sm text-muted-foreground">{data.error || 'No table of transactions was found.'}</p>
  const byColumn = chosen ?? invertLayout(data.proposed)
  const { layout, problem } = layoutFrom(byColumn)

  return (
    <div className="grid gap-3">
      <p className="text-sm text-muted-foreground">
        These are the first rows of the table found ({data.total_rows} rows in all). Say what each column is, then try again. Your choice is
        checked against the statement’s own balances before anything is imported.
      </p>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-xs">
          <caption className="sr-only">First rows of the statement table</caption>
          <thead>
            <tr>
              {Array.from({ length: data.width }, (_, column) => (
                <th key={column} scope="col" className="p-1 text-left align-top font-medium">
                  <Select
                    aria-label={`What column ${column + 1} is`}
                    value={byColumn[column] ?? ''}
                    onChange={(e) => setChosen({ ...byColumn, [column]: e.target.value })}
                  >
                    {ROLES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, i) => (
              <tr key={i} className="border-t">
                {row.map((cell, c) => (
                  <td key={c} className="max-w-48 truncate p-1">{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {problem && <p role="alert" className="text-sm text-destructive">{problem}</p>}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onBack}>Back</Button>
        <Button disabled={!layout} onClick={() => layout && onTry(layout)}>Try again with these columns</Button>
      </div>
    </div>
  )
}
