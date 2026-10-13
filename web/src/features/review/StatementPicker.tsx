// Which bank statements the review is looking at: one, several, or all. A few statements are chips you tick on and off, each with the rows it has
// waiting in this stage; more than that are a menu of tick boxes. "All statements" clears the choice.

import { ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import { selectionSummary, toggled, type StatementChoice } from './statementChoices'

const ALL = 'all'
/** Up to this many statements are shown as chips; more would not fit on a line, so they are a menu. */
const CHIPS_UP_TO = 4

export function StatementPicker({
  choices,
  selection,
  total,
  onChange,
}: {
  choices: StatementChoice[]
  /** The statements chosen, or null for all of them. */
  selection: string[] | null
  /** Rows waiting in this stage across every statement. */
  total: number
  /** Called with the new address value: `all`, or the ids joined with commas. */
  onChange: (asked: string) => void
}) {
  const chosen = (id: string) => (selection ? selection.includes(id) : false)
  const label = (c: StatementChoice) => `${c.label} · ${c.count}`
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
      <span className="text-muted-foreground">Statements:</span>
      {choices.length <= CHIPS_UP_TO ? (
        <div role="group" aria-label="Statements to review" className="flex flex-wrap items-center gap-1.5">
          {choices.map((c) => (
            <button
              key={c.id}
              type="button"
              aria-pressed={chosen(c.id)}
              onClick={() => onChange(toggled(selection, c.id, choices))}
              className={cn(
                'rounded-full border px-3 py-1 text-sm transition-colors duration-150',
                chosen(c.id) ? 'border-primary bg-selected font-medium text-heading' : 'hover:bg-hover',
              )}
            >
              {label(c)}
            </button>
          ))}
          <button
            type="button"
            aria-pressed={selection === null}
            onClick={() => onChange(ALL)}
            className={cn('rounded-full border px-3 py-1 text-sm transition-colors duration-150', selection === null ? 'border-primary bg-selected font-medium text-heading' : 'hover:bg-hover')}
          >
            All statements · {total}
          </button>
        </div>
      ) : (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="h-9 gap-2 rounded-full px-3.5">
              {selection === null ? 'All statements' : selection.length === 1 ? choices.find((c) => c.id === selection[0])?.label : `${selection.length} statements`}
              <ChevronDown className="size-4 text-muted-foreground" aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" aria-label="Choose statements">
            <DropdownMenuCheckboxItem checked={selection === null} onSelect={(e) => e.preventDefault()} onCheckedChange={() => onChange(ALL)}>
              All statements · {total}
            </DropdownMenuCheckboxItem>
            <DropdownMenuSeparator />
            {choices.map((c) => (
              <DropdownMenuCheckboxItem key={c.id} checked={chosen(c.id)} onSelect={(e) => e.preventDefault()} onCheckedChange={() => onChange(toggled(selection, c.id, choices))}>
                {label(c)}
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      <span className="text-muted-foreground" aria-live="polite">
        {selectionSummary(selection, choices)}
      </span>
    </div>
  )
}
