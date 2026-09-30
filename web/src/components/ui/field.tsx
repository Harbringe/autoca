import { CircleX } from 'lucide-react'
import { useId, type FormEvent, type ReactNode } from 'react'
import { applyMask, type Mask } from '@/lib/masks'
import { Label } from './label'

interface FieldProps {
  id: string
  'aria-invalid': boolean
  'aria-describedby'?: string
}

/** Spread onto an <Input> as the second argument's props: `{(p, m) => <Input {...p} {...m} />}`. */
export interface MaskProps {
  onInput?: (e: FormEvent<HTMLElement>) => void
  autoCapitalize?: string
  maxLength?: number
}

/**
 * A label above, its input, a hint below, and the server's complaint about it (with an icon), wired
 * together for screen readers. `mask` uppercases and limits the input as it is typed.
 */
export function Field({
  label,
  error,
  hint,
  mask,
  children,
}: {
  label: string
  error?: string
  hint?: string
  mask?: Mask
  children: (props: FieldProps, maskProps: MaskProps) => ReactNode
}) {
  const id = useId()
  const note = `${id}-note`
  const masked: MaskProps = mask
    ? {
        onInput: (e) => {
          const el = e.currentTarget as HTMLInputElement
          const next = applyMask(mask, el.value)
          if (next !== el.value) el.value = next
        },
        autoCapitalize: 'characters',
        maxLength: mask === 'pan' ? 10 : 15,
      }
    : {}
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children({ id, 'aria-invalid': !!error, 'aria-describedby': error || hint ? note : undefined }, masked)}
      {error ? (
        <p id={note} className="flex items-start gap-1.5 text-[13px] text-destructive">
          <CircleX className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {error}
        </p>
      ) : (
        hint && (
          <p id={note} className="text-[13px] text-muted-foreground">
            {hint}
          </p>
        )
      )}
    </div>
  )
}
