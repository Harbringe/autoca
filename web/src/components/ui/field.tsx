import { useId, type ReactNode } from 'react'
import { Label } from './label'

/** A label, its input, and the server's complaint about it, wired together for screen readers. */
export function Field({
  label,
  error,
  hint,
  children,
}: {
  label: string
  error?: string
  hint?: string
  children: (props: { id: string; 'aria-invalid': boolean; 'aria-describedby'?: string }) => ReactNode
}) {
  const id = useId()
  const note = `${id}-note`
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children({ id, 'aria-invalid': !!error, 'aria-describedby': error || hint ? note : undefined })}
      {(error || hint) && (
        <p id={note} className={error ? 'text-[13px] text-destructive' : 'text-[13px] text-muted-foreground'}>
          {error ?? hint}
        </p>
      )}
    </div>
  )
}
