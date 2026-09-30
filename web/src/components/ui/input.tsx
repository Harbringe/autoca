import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

export function Input({ className, type = 'text', ...props }: ComponentProps<'input'>) {
  return (
    <input
      type={type}
      className={cn(
        'h-9 w-full min-w-0 rounded-md border border-input bg-card px-3 text-sm transition-colors placeholder:text-faint disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive',
        className,
      )}
      {...props}
    />
  )
}
