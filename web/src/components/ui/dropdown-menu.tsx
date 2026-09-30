import { Check } from 'lucide-react'
import { DropdownMenu as Primitive } from 'radix-ui'
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

export const DropdownMenu = Primitive.Root
export const DropdownMenuTrigger = Primitive.Trigger
export const DropdownMenuRadioGroup = Primitive.RadioGroup

export function DropdownMenuContent({ className, sideOffset = 6, ...props }: ComponentProps<typeof Primitive.Content>) {
  return (
    <Primitive.Portal>
      <Primitive.Content
        sideOffset={sideOffset}
        className={cn(
          'z-50 min-w-52 overflow-hidden rounded-lg border bg-popover p-1 text-popover-foreground shadow-[var(--shadow-float)] data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:duration-[120ms]',
          className,
        )}
        {...props}
      />
    </Primitive.Portal>
  )
}

const item =
  'relative flex cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-hover data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&_svg]:size-4'

export function DropdownMenuItem({ className, ...props }: ComponentProps<typeof Primitive.Item>) {
  return <Primitive.Item className={cn(item, className)} {...props} />
}

export function DropdownMenuRadioItem({ className, children, ...props }: ComponentProps<typeof Primitive.RadioItem>) {
  return (
    <Primitive.RadioItem className={cn(item, 'pl-8', className)} {...props}>
      <span className="absolute left-2 grid size-4 place-items-center">
        <Primitive.ItemIndicator>
          <Check />
        </Primitive.ItemIndicator>
      </span>
      {children}
    </Primitive.RadioItem>
  )
}

export function DropdownMenuCheckboxItem({ className, children, ...props }: ComponentProps<typeof Primitive.CheckboxItem>) {
  return (
    <Primitive.CheckboxItem className={cn(item, 'pl-8', className)} {...props}>
      <span className="absolute left-2 grid size-4 place-items-center">
        <Primitive.ItemIndicator>
          <Check />
        </Primitive.ItemIndicator>
      </span>
      {children}
    </Primitive.CheckboxItem>
  )
}

export function DropdownMenuLabel({ className, ...props }: ComponentProps<typeof Primitive.Label>) {
  return <Primitive.Label className={cn('px-2 py-1.5 text-xs font-medium text-muted-foreground', className)} {...props} />
}

export function DropdownMenuSeparator({ className, ...props }: ComponentProps<typeof Primitive.Separator>) {
  return <Primitive.Separator className={cn('-mx-1 my-1 h-px bg-border', className)} {...props} />
}
