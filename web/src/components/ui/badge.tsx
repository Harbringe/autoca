import { cva, type VariantProps } from 'class-variance-authority'
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

const variants = cva('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap', {
  variants: {
    tone: {
      neutral: 'border-transparent bg-muted text-muted-foreground',
      success: 'border-transparent bg-success/12 text-success',
      warning: 'border-transparent bg-warning/14 text-warning',
      danger: 'border-transparent bg-destructive/12 text-destructive',
      info: 'border-transparent bg-info/12 text-info',
      outline: 'text-foreground',
    },
  },
  defaultVariants: { tone: 'neutral' },
})

export function Badge({ className, tone, ...props }: ComponentProps<'span'> & VariantProps<typeof variants>) {
  return <span className={cn(variants({ tone }), className)} {...props} />
}
