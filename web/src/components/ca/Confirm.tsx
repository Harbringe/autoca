// "Are you sure?", said properly: what will happen, to how much, and whether it can be undone.
//
// Every irreversible or consequential action in the books goes through this -- posting,
// sign-off, reopening, removing a statement or an entry. A note can be asked for, and
// made compulsory where the audit trail needs a reason.

import { useState, type ReactNode } from 'react'
import { messageOf } from '@/api/errors'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/controls'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'

export interface ConfirmProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  children?: ReactNode
  confirmLabel: string
  destructive?: boolean
  /** Ask for a note. "required" refuses to continue without one. */
  note?: 'optional' | 'required'
  noteLabel?: string
  onConfirm: (note: string) => Promise<unknown>
  /** Refuse to continue, and say why (shown above the buttons). */
  blockedReason?: ReactNode
}

export function Confirm({
  open,
  onOpenChange,
  title,
  children,
  confirmLabel,
  destructive,
  note,
  noteLabel,
  onConfirm,
  blockedReason,
}: ConfirmProps) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function go() {
    setBusy(true)
    setError(null)
    try {
      await onConfirm(text.trim())
      setText('')
      onOpenChange(false)
    } catch (e) {
      setError(messageOf(e))
    } finally {
      setBusy(false)
    }
  }

  const blocked = (note === 'required' && !text.trim()) || !!blockedReason

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {children && <DialogDescription asChild><div className="grid gap-2 text-sm text-muted-foreground">{children}</div></DialogDescription>}
        </DialogHeader>
        {note && (
          <Field label={noteLabel ?? (note === 'required' ? 'Reason (required)' : 'Note (optional)')}>
            {(props) => <Textarea {...props} autoFocus value={text} onChange={(e) => setText(e.target.value)} maxLength={1000} />}
          </Field>
        )}
        {blockedReason && <div className="rounded-md border border-accent-edge bg-accent p-3 text-sm">{blockedReason}</div>}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant={destructive ? 'destructive' : 'primary'} onClick={go} disabled={busy || blocked} autoFocus={!note}>
            {busy ? 'Working…' : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
