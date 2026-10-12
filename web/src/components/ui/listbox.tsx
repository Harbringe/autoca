import { Check, ChevronDown } from 'lucide-react'
import { Select as Primitive } from 'radix-ui'
import { cn } from '@/lib/utils'

// Radix does not allow an empty string as an item value, so "nothing chosen" travels as this and is turned back at the edge.
const NONE = '__none__'

export interface ListboxOption {
  value: string
  label: string
}

/**
 * A dropdown drawn in the app's own colours, for the few choices that are prominent enough that the browser's
 * grey system list looks wrong beside the page. `value` and `onValueChange` use '' for "nothing chosen".
 * Spread a <Field>'s props onto it, as with <Input>.
 */
export function Listbox({
  value,
  onValueChange,
  options,
  disabled,
  className,
  ...aria
}: {
  value: string
  onValueChange: (value: string) => void
  options: ListboxOption[]
  disabled?: boolean
  className?: string
  id?: string
  'aria-label'?: string
  'aria-invalid'?: boolean
  'aria-describedby'?: string
}) {
  return (
    <Primitive.Root value={value === '' ? NONE : value} onValueChange={(v) => onValueChange(v === NONE ? '' : v)} disabled={disabled}>
      <Primitive.Trigger
        {...aria}
        className={cn(
          'flex h-12 w-full items-center justify-between gap-3 rounded-lg border border-input bg-card px-4 dark:border-border-strong dark:bg-background text-left text-base text-heading outline-none transition-colors hover:bg-hover focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive data-[state=open]:border-ring',
          className,
        )}
      >
        <span className="min-w-0 truncate">
          <Primitive.Value />
        </span>
        <Primitive.Icon>
          <ChevronDown className="size-4 text-muted-foreground" aria-hidden />
        </Primitive.Icon>
      </Primitive.Trigger>
      <Primitive.Portal>
        <Primitive.Content
          position="popper"
          sideOffset={6}
          collisionPadding={8}
          className="z-50 max-h-72 w-(--radix-select-trigger-width) min-w-48 overflow-hidden rounded-lg border border-border-strong bg-popover text-popover-foreground shadow-[var(--shadow-float)] data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:duration-[120ms]"
        >
          <Primitive.Viewport className="p-1.5">
            {options.map((o) => (
              <Primitive.Item
                key={o.value}
                value={o.value === '' ? NONE : o.value}
                className="relative flex min-h-10 cursor-pointer select-none items-center rounded-md py-2 pl-9 pr-3 text-[15px] outline-none data-[disabled]:opacity-50 data-[highlighted]:bg-hover data-[state=checked]:font-semibold data-[state=checked]:text-heading"
              >
                <Primitive.ItemIndicator className="absolute left-3 inline-flex">
                  <Check className="size-4 text-primary" aria-hidden />
                </Primitive.ItemIndicator>
                <Primitive.ItemText>{o.label}</Primitive.ItemText>
              </Primitive.Item>
            ))}
          </Primitive.Viewport>
        </Primitive.Content>
      </Primitive.Portal>
    </Primitive.Root>
  )
}
