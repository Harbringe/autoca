import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

export function Select({ className, ...props }: ComponentProps<'select'>) {
  return (
    <select
      className={cn(
        'h-9 w-full rounded-md border border-input bg-card px-2.5 text-sm shadow-xs disabled:opacity-50 aria-invalid:border-destructive',
        className,
      )}
      {...props}
    />
  )
}

export function Textarea({ className, ...props }: ComponentProps<'textarea'>) {
  return (
    <textarea
      className={cn(
        'min-h-20 w-full rounded-md border border-input bg-card px-3 py-2 text-sm shadow-xs aria-invalid:border-destructive',
        className,
      )}
      {...props}
    />
  )
}

export function Checkbox({ label, className, ...props }: ComponentProps<'input'> & { label?: string }) {
  const box = <input type="checkbox" className={cn('size-4 accent-[var(--primary)]', !label && className)} {...props} />
  if (!label) return box
  return (
    <label className={cn('flex cursor-pointer items-center gap-2 text-sm', className)}>
      {box}
      {label}
    </label>
  )
}

/** Table classes, so every grid in the app lines up the same way. */
export const tbl = {
  wrap: 'relative overflow-x-auto rounded-lg border bg-card',
  table: 'w-full text-left text-sm',
  head: 'border-b bg-muted/50 text-[13px] text-muted-foreground',
  th: 'px-3 py-2 font-medium whitespace-nowrap',
  thNum: 'px-3 py-2 font-medium whitespace-nowrap text-right',
  row: 'h-(--row-h) border-b last:border-b-0',
  td: 'px-3 py-1',
  tdNum: 'px-3 py-1 text-right num whitespace-nowrap',
  foot: 'border-t-2 bg-muted/40 font-semibold',
}
