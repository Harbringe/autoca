// A ledger the assistant thought a row belongs in but was not sure enough to open. Nothing has been created: the row sits in the
// closest ledger it had, and a person decides here to open the suggested one (and place the row in it), or to leave it.

import { Sparkles } from 'lucide-react'
import type { Classification } from '@/api/types'
import { Button } from '@/components/ui/button'
import { plural } from '@/lib/format'

export function LedgerIdea({
  suggestion,
  placedIn,
  canCreate,
  busy,
  onPlaceExisting,
  onCreate,
}: {
  suggestion: NonNullable<Classification['suggested_ledger']>
  /** Where the row sits now, in the closest ledger the client had. */
  placedIn: string | null
  /** May this person open a new ledger. Without it the idea is shown as words. */
  canCreate: boolean
  busy: boolean
  onPlaceExisting: (ledgerId: string) => void
  onCreate: () => void
}) {
  const others = suggestion.rows_sharing > 0 ? `${plural(suggestion.rows_sharing, 'other waiting row')} carry the same suggestion.` : ''
  return (
    <div className="grid gap-2 rounded-md border border-info/30 bg-info-bg p-3 text-sm" aria-label="Suggested ledger">
      <div>
        <Sparkles className="mr-1.5 inline size-4 text-info" aria-hidden />
        {suggestion.existing_ledger ? (
          <>
            The assistant thinks this belongs in <strong>{suggestion.existing_name}</strong>
            {placedIn ? <>, not {placedIn}</> : null}.
          </>
        ) : (
          <>
            The assistant suggests a new ledger, <strong>{suggestion.name}</strong> ({suggestion.group_display}). It was not sure enough to open one
            {placedIn ? <>, so the row is in {placedIn} for now</> : null}.
          </>
        )}
        {others ? <span className="block text-xs text-muted-foreground">{others}</span> : null}
      </div>
      {suggestion.existing_ledger ? (
        <div>
          <Button size="sm" onClick={() => onPlaceExisting(suggestion.existing_ledger!)} disabled={busy}>
            Place in {suggestion.existing_name}
          </Button>
        </div>
      ) : canCreate ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={onCreate} disabled={busy}>
            Create “{suggestion.name}” and place this row
          </Button>
          <span className="text-xs text-muted-foreground">You can change the name or the kind before it is created.</span>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">Someone who can add ledgers can create it. Meanwhile choose another ledger below.</p>
      )}
    </div>
  )
}
