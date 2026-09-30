import { cva, type VariantProps } from 'class-variance-authority'
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

// Flat: a warm 1px edge and no shadow. Only things that float (menus, dialogs, toasts) get one.
const card = cva('rounded-lg border bg-card text-card-foreground', {
  variants: {
    tone: {
      plain: '',
      attention: 'border-accent-edge bg-accent text-accent-foreground',
      danger: 'border-destructive/40 bg-destructive-bg',
      info: 'border-info/30 bg-info-bg',
      success: 'border-success/30 bg-success-bg',
    },
  },
  defaultVariants: { tone: 'plain' },
})

export function Card({ className, tone, ...props }: ComponentProps<'div'> & VariantProps<typeof card>) {
  return <div className={cn(card({ tone }), className)} {...props} />
}
export function CardHeader({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('flex flex-col gap-1 p-5 pb-3', className)} {...props} />
}
export function CardTitle({ className, ...props }: ComponentProps<'h2'>) {
  return <h2 className={cn('text-[15px] font-semibold leading-snug text-heading', className)} {...props} />
}
export function CardDescription({ className, ...props }: ComponentProps<'p'>) {
  return <p className={cn('text-[13px] text-muted-foreground', className)} {...props} />
}
export function CardContent({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('p-5 pt-2', className)} {...props} />
}
