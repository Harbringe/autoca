import { cva, type VariantProps } from 'class-variance-authority'
import { AlertTriangle, Check, CircleX, Info, Sparkles } from 'lucide-react'
import type { ComponentProps, ReactNode } from 'react'
import { cn } from '@/lib/utils'

// Status is words plus a shape, never colour alone. The tone decides the icon unless one is given.
// `success` and `warning` are the older names for `done` and `attention` and mean the same thing.
const variants = cva(
  'inline-flex h-[22px] items-center gap-1 rounded-sm border px-2 text-xs font-medium whitespace-nowrap [&_svg]:size-3 [&_svg]:shrink-0',
  {
    variants: {
      tone: {
        neutral: 'border-transparent bg-muted text-muted-foreground',
        done: 'border-transparent bg-success-bg text-success',
        success: 'border-transparent bg-success-bg text-success',
        attention: 'border-accent-edge bg-accent text-accent-foreground',
        warning: 'border-accent-edge bg-accent text-accent-foreground',
        danger: 'border-transparent bg-destructive-bg text-destructive',
        info: 'border-transparent bg-info-bg text-info',
        assistant: 'border-transparent bg-info-bg text-info',
        outline: 'text-foreground',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
)

type Tone = NonNullable<VariantProps<typeof variants>['tone']>

const ICONS: Partial<Record<Tone, ReactNode>> = {
  neutral: <span className="size-1.5 rounded-full bg-current" aria-hidden />,
  done: <Check aria-hidden />,
  success: <Check aria-hidden />,
  attention: <AlertTriangle aria-hidden />,
  warning: <AlertTriangle aria-hidden />,
  danger: <CircleX aria-hidden />,
  info: <Info aria-hidden />,
  assistant: <Sparkles aria-hidden />,
}

export function Badge({
  className,
  tone,
  icon,
  children,
  ...props
}: ComponentProps<'span'> & VariantProps<typeof variants> & { icon?: ReactNode | false }) {
  const shown = icon === false ? null : (icon ?? ICONS[tone ?? 'neutral'])
  return (
    <span className={cn(variants({ tone }), className)} {...props}>
      {shown}
      {children}
    </span>
  )
}

/** A count in a pill: the only pill in the product. */
export function CountChip({ className, ...props }: ComponentProps<'span'>) {
  return (
    <span
      className={cn(
        'num inline-flex min-w-5 items-center justify-center rounded-full border border-accent-edge bg-accent px-1.5 text-xs font-semibold text-accent-foreground',
        className,
      )}
      {...props}
    />
  )
}
