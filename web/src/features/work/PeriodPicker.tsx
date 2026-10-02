// The period chips (This month, Last month, This financial year, Custom dates) and the custom
// date form. Shared by Staff performance and the Dashboard; the caller decides where the choice
// is kept (the address, or its own state).

import { useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { DateInput } from '@/components/ui/date-input'
import { formatDate, parseDate } from '@/lib/format'
import { PERIOD_LABEL, rangeProblem, type PeriodKey, type Range } from '@/lib/period'

const PRESETS: PeriodKey[] = ['month', 'last', 'fy', 'custom']

export function PeriodPicker({
  value,
  range,
  onPick,
}: {
  value: PeriodKey
  range: Range | null
  onPick: (next: { period: PeriodKey; from?: string; to?: string }) => void
}) {
  const [from, setFrom] = useState(range ? formatDate(range.from) : '')
  const [to, setTo] = useState(range ? formatDate(range.to) : '')
  const [error, setError] = useState<string | null>(null)

  function apply(e: FormEvent) {
    e.preventDefault()
    const f = parseDate(from)
    const t = parseDate(to)
    const problem = rangeProblem(f && t ? { from: f, to: t } : null)
    setError(problem)
    if (!problem) onPick({ period: 'custom', from: f!, to: t! })
  }

  return (
    <div className="grid gap-2">
      <div role="group" aria-label="Period" className="flex flex-wrap gap-1.5">
        {PRESETS.map((p) => (
          <Button
            key={p}
            size="sm"
            variant={p === value ? 'primary' : 'outline'}
            aria-pressed={p === value}
            onClick={() => (p === 'custom' ? onPick({ period: 'custom', from: range?.from, to: range?.to }) : onPick({ period: p, from: undefined, to: undefined }))}
          >
            {PERIOD_LABEL[p]}
          </Button>
        ))}
      </div>
      {value === 'custom' && (
        <form onSubmit={apply} className="flex flex-wrap items-start gap-2" noValidate>
          <label className="grid gap-1 text-[13px] text-muted-foreground">
            From
            <DateInput aria-invalid={!!error} className="w-36" value={from} onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label className="grid gap-1 text-[13px] text-muted-foreground">
            To
            <DateInput aria-invalid={!!error} className="w-36" value={to} onChange={(e) => setTo(e.target.value)} />
          </label>
          <Button type="submit" size="md" className="mt-5">
            Show
          </Button>
          {error && (
            <p role="alert" className="mt-5 text-sm text-destructive">
              {error}
            </p>
          )}
        </form>
      )}
      {range && (
        <p className="text-[13px] text-muted-foreground">
          <span className="num">{formatDate(range.from)}</span> to <span className="num">{formatDate(range.to)}</span>
        </p>
      )}
    </div>
  )
}
