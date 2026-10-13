import { AlertTriangle, Check, CircleX, Info, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { AUTO_CLOSE_MS, toast, useNotes, type Note, type NoteKind } from '@/lib/toast'
import { cn } from '@/lib/utils'

/** More than this many and the rest fold into a "+N more" button. */
const VISIBLE = 3

const MARK: Record<NoteKind, { icon: typeof Check; tile: string }> = {
  success: { icon: Check, tile: 'bg-success-bg text-success' },
  info: { icon: Info, tile: 'bg-info-bg text-info' },
  warning: { icon: AlertTriangle, tile: 'bg-accent text-accent-foreground' },
  error: { icon: CircleX, tile: 'bg-destructive-bg text-destructive' },
}

function NoteCard({ note }: { note: Note }) {
  // The clock stops while the pointer or the keyboard is on the card, so it can be read.
  const [held, setHeld] = useState(false)
  useEffect(() => {
    if (note.sticky || held) return
    const timer = setTimeout(() => toast.dismiss(note.id), AUTO_CLOSE_MS)
    return () => clearTimeout(timer)
  }, [note.id, note.sticky, held])
  const { icon: Icon, tile } = MARK[note.kind]
  return (
    <div
      role={note.sticky ? 'alert' : 'status'}
      onMouseEnter={() => setHeld(true)}
      onMouseLeave={() => setHeld(false)}
      onFocus={() => setHeld(true)}
      onBlur={() => setHeld(false)}
      className="fade-in flex shrink-0 items-start gap-3 rounded-xl border bg-card py-2.5 pl-3 pr-1.5 text-sm shadow-lg"
    >
      <span aria-hidden className={cn('mt-0.5 grid size-6 shrink-0 place-items-center rounded-full', tile)}>
        <Icon className="size-3.5" />
      </span>
      {/* Long words, addresses and error text wrap inside the card; a very long description scrolls inside it rather than stretching the stack. */}
      <div className="min-w-0 flex-1 [overflow-wrap:anywhere]">
        <p className="font-medium text-heading">{note.title}</p>
        {note.description && <p className="max-h-32 overflow-y-auto overscroll-contain text-[13px] text-muted-foreground">{note.description}</p>}
      </div>
      {note.sticky && <span className="mt-0.5 shrink-0 rounded-sm border px-1.5 text-[11px] font-medium text-muted-foreground">Stays</span>}
      <Button variant="ghost" size="icon" className="size-7 shrink-0" aria-label="Close notification" onClick={() => toast.dismiss(note.id)}>
        <X className="size-4" aria-hidden />
      </Button>
    </div>
  )
}

/**
 * The stack of notifications at the bottom right. Successes go by themselves; warnings and errors stay until
 * closed and say so. Three show at a time, the rest fold into "+N more", and "Clear all" closes them together.
 * The container is always present so a screen reader is already listening when a message arrives.
 */
export function Notifications() {
  const notes = useNotes()
  const [expanded, setExpanded] = useState(false)
  // Once few enough are left to show, folding starts again: the next crowd does not arrive already unfolded.
  useEffect(() => {
    if (expanded && notes.length <= VISIBLE) setExpanded(false)
  }, [expanded, notes.length])
  const shown = expanded ? notes : notes.slice(0, VISIBLE)
  const hidden = notes.length - shown.length
  return (
    // The stack never grows past the window: the cards scroll inside it, and the count, "Clear all" and "+N more" stay in reach.
    <div
      aria-live="polite"
      className="pointer-events-none fixed bottom-[max(1rem,env(safe-area-inset-bottom))] right-4 z-[100] flex max-h-[calc(100svh-2rem)] w-[min(380px,calc(100vw-2rem))] flex-col gap-2.5 [&>*]:pointer-events-auto"
    >
      {notes.length > 1 && (
        <div className="flex shrink-0 items-center justify-between gap-2 px-1 text-xs text-muted-foreground">
          <span className="rounded-md bg-background/80 px-1.5 py-0.5">{notes.length} notifications</span>
          <button type="button" className="rounded-md bg-background/80 px-1.5 py-0.5 font-medium text-link underline underline-offset-2" onClick={() => toast.dismiss()}>
            Clear all
          </button>
        </div>
      )}
      <div className="flex min-h-0 flex-col gap-2.5 overflow-y-auto overscroll-contain">
        {shown.map((note) => (
          <NoteCard key={note.id} note={note} />
        ))}
      </div>
      {hidden > 0 && (
        <Button variant="secondary" size="sm" className="shrink-0 self-end rounded-full" onClick={() => setExpanded(true)}>
          +{hidden} more
        </Button>
      )}
      {expanded && notes.length > VISIBLE && (
        <Button variant="secondary" size="sm" className="shrink-0 self-end rounded-full" onClick={() => setExpanded(false)}>
          Show fewer
        </Button>
      )}
    </div>
  )
}
