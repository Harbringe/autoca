import { X } from 'lucide-react'
import { Dialog as Primitive } from 'radix-ui'
import { useLayoutEffect, useRef, type ComponentProps, type MutableRefObject } from 'react'
import { cn } from '@/lib/utils'

export const Dialog = Primitive.Root
export const DialogTrigger = Primitive.Trigger
export const DialogClose = Primitive.Close

// Widths: 448 (confirm, the default), 560 (form: max-w-xl), 720 (wide: max-w-3xl). Under 640px a
// dialog is a full-screen sheet. Opacity is the only motion, and it is off under reduced motion.
export function DialogContent({ className, children, onCloseAutoFocus, ...props }: ComponentProps<typeof Primitive.Content>) {
  // Radix returns focus to its <Trigger>. Most dialogs here are opened from state (a button sets
  // `open`), so there is no Trigger and focus would drop to the top of the page. Remember what had
  // focus when the dialog opened and put it back; if that element is gone, land on the page's main
  // region so the next Tab starts in the content, not the sidebar.
  const opener = useRef<HTMLElement | null>(null)
  return (
    <Primitive.Portal>
      <Primitive.Overlay className="fixed inset-0 z-50 bg-black/45 data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:duration-[120ms]" />
      <Primitive.Content
        className={cn(
          'fixed left-1/2 top-1/2 z-50 grid max-h-[calc(100svh-2rem)] w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 gap-4 overflow-y-auto rounded-xl border bg-popover p-6 text-popover-foreground shadow-[var(--shadow-float)] outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:duration-[120ms]',
          'max-sm:left-0 max-sm:top-0 max-sm:content-start max-sm:h-svh max-sm:max-h-none max-sm:w-full max-sm:max-w-none max-sm:translate-x-0 max-sm:translate-y-0 max-sm:rounded-none max-sm:border-0',
          className,
        )}
        onCloseAutoFocus={(event) => {
          onCloseAutoFocus?.(event)
          if (event.defaultPrevented) return
          const target = opener.current
          if (target?.isConnected) {
            event.preventDefault()
            target.focus()
          } else {
            event.preventDefault()
            document.getElementById('content')?.focus()
          }
        }}
        {...props}
      >
        <RememberOpener into={opener} />
        {children}
        <Primitive.Close className="absolute right-3 top-3 grid size-8 place-items-center rounded-md text-muted-foreground hover:bg-hover hover:text-foreground" aria-label="Close">
          <X className="size-4" />
        </Primitive.Close>
      </Primitive.Content>
    </Primitive.Portal>
  )
}

export function DialogHeader({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('flex flex-col gap-1.5 pr-6', className)} {...props} />
}
export function DialogFooter({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('flex justify-end gap-2', className)} {...props} />
}
export function DialogTitle({ className, ...props }: ComponentProps<typeof Primitive.Title>) {
  return <Primitive.Title className={cn('text-lg font-semibold leading-tight text-heading', className)} {...props} />
}
export function DialogDescription({ className, ...props }: ComponentProps<typeof Primitive.Description>) {
  return <Primitive.Description className={cn('text-sm text-muted-foreground', className)} {...props} />
}

/** Notes which element had focus at the moment the dialog's content mounted, before focus moves into it. */
function RememberOpener({ into }: { into: MutableRefObject<HTMLElement | null> }) {
  // A layout effect runs before the focus scope's own effect moves focus into the dialog.
  useLayoutEffect(() => {
    const active = document.activeElement
    into.current = active instanceof HTMLElement && active !== document.body ? active : null
  }, [into])
  return null
}
