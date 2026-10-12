import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * An on/off switch. One transform moves the thumb and the track changes colour, so it costs nothing on an old machine; under
 * reduced motion the global rule makes it instant. `label` names it for a screen reader.
 */
export function Switch({
  checked,
  onChange,
  label,
  disabled,
  pending,
  className,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  label: string
  disabled?: boolean
  /** The change is on its way to the server: the switch has already moved, and a small spinner shows until it is saved. */
  pending?: boolean
  className?: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      aria-busy={pending || undefined}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-60',
        checked ? 'border-primary bg-primary' : 'border-border-strong bg-muted',
        className,
      )}
    >
      <span
        aria-hidden
        className={cn(
          'grid size-[18px] place-items-center rounded-full transition-transform duration-150 ease-out',
          checked ? 'translate-x-[22px] bg-white' : 'translate-x-[3px] bg-muted-foreground',
        )}
      >
        {pending && <Loader2 className={cn('size-3 animate-spin', checked ? 'text-primary' : 'text-muted')} />}
      </span>
    </button>
  )
}
