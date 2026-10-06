import { Popover as Primitive } from 'radix-ui'
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

export const Popover = Primitive.Root
export const PopoverTrigger = Primitive.Trigger
export const PopoverClose = Primitive.Close

/** A floating panel anchored to its trigger: Esc closes it and focus goes back to the trigger. */
export function PopoverContent({ className, sideOffset = 8, collisionPadding = 8, ...props }: ComponentProps<typeof Primitive.Content>) {
  return (
    <Primitive.Portal>
      <Primitive.Content
        sideOffset={sideOffset}
        collisionPadding={collisionPadding}
        className={cn(
          'z-50 overflow-hidden rounded-lg border bg-popover text-popover-foreground shadow-[var(--shadow-float)] outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:duration-[120ms]',
          className,
        )}
        {...props}
      />
    </Primitive.Portal>
  )
}
