// Which bank statement the review is looking at. A few statements are chips with the rows each has waiting; many are a menu.

import { GlideChips } from '@/components/ui/glide-chips'
import { Select } from '@/components/ui/controls'
import { plural } from '@/lib/format'
import type { StatementChoice } from './statementChoices'

const ALL = 'all'
/** Up to this many statements are shown as chips; more would not fit on a line, so they are a menu. */
const CHIPS_UP_TO = 4

export function StatementPicker({
  choices,
  active,
  total,
  onChange,
}: {
  choices: StatementChoice[]
  /** The statement shown, or null for all of them. */
  active: string | null
  /** Rows waiting in the stage across every statement. */
  total: number
  onChange: (statement: string) => void
}) {
  const options = [
    ...choices.map((c) => ({ value: c.id, label: `${c.label} · ${c.count}` })),
    { value: ALL, label: `All statements · ${total}` },
  ]
  const current = choices.find((c) => c.id === active)
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
      <span className="text-muted-foreground">Statement:</span>
      {choices.length <= CHIPS_UP_TO ? (
        <GlideChips label="Statement" value={active ?? ALL} onChange={onChange} options={options} />
      ) : (
        <Select aria-label="Statement" className="h-9 w-auto min-w-64" value={active ?? ALL} onChange={(e) => onChange(e.target.value)}>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      )}
      <span className="text-muted-foreground" aria-live="polite">
        {current ? `${current.period} · ${plural(current.count, 'row')} waiting` : `${plural(choices.length, 'statement')}, worked through one at a time or all together`}
      </span>
    </div>
  )
}
