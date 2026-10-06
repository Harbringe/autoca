// How often this client's books are sealed, and when the next seal is due.
//
// A senior's approval says the books are good and locks nothing. The seal is the permanent lock, and it goes on only at the
// end of the period the firm has promised this client: each quarter, half-year or year. Books run April to March.

import { useState } from 'react'
import { toast } from 'sonner'
import { raw } from '@/api/client'
import { messageOf } from '@/api/errors'
import { useInvalidateClient, V1 } from '@/api/queries/clients'
import type { BooksStatus } from '@/api/types'
import { Card } from '@/components/ui/card'
import { Select } from '@/components/ui/controls'
import { formatDate } from '@/lib/format'

const PERIODS = [
  ['QUARTERLY', 'Quarterly: 30 Jun, 30 Sep, 31 Dec, 31 Mar'],
  ['HALF_YEARLY', 'Half-yearly: 30 Sep, 31 Mar'],
  ['YEARLY', 'Yearly: 31 Mar'],
] as const

export function SealSchedule({ clientId, books, mayChange }: { clientId: string; books: BooksStatus; mayChange: boolean }) {
  const invalidate = useInvalidateClient(clientId)
  const [busy, setBusy] = useState(false)

  async function change(period: string) {
    setBusy(true)
    try {
      await raw.patch(`${V1}/clients/${clientId}/`, { close_period: period })
      await invalidate()
      toast.success('Sealing schedule changed')
    } catch (e) {
      toast.error(messageOf(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="grid gap-2 p-4" aria-label="Sealing schedule">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium">Sealing schedule</div>
          <p className="text-sm text-muted-foreground">
            The books are sealed (locked for good) at the end of each period, after the senior has approved them.
            {books.next_seal_date ? ` Next sealing date: ${formatDate(books.next_seal_date)}.` : ''}
          </p>
        </div>
        <Select
          aria-label="How often the books are sealed"
          className="w-80"
          value={books.close_period}
          disabled={!mayChange || busy}
          onChange={(e) => void change(e.target.value)}
        >
          {PERIODS.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </Select>
      </div>
    </Card>
  )
}
