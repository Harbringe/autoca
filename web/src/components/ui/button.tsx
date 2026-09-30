import { cva, type VariantProps } from 'class-variance-authority'
import { Loader2 } from 'lucide-react'
import { Slot } from 'radix-ui'
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

// One primary per surface (a page header, a dialog footer, or the current checklist step), never two.
// `secondary` and `outline` are the same white button with a visible edge; `destructive` is solid red
// and belongs inside a confirm dialog.
const variants = cva(
  'inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 aria-busy:pointer-events-none [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        primary: 'bg-primary text-primary-foreground hover:bg-primary-hover',
        secondary: 'border border-input bg-card text-foreground hover:bg-hover',
        outline: 'border border-input bg-card text-foreground hover:bg-hover',
        ghost: 'hover:bg-hover',
        destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
        link: 'text-link underline-offset-4 hover:underline',
      },
      size: {
        sm: 'h-8 px-3 text-[13px]',
        md: 'h-9 px-4',
        lg: 'h-11 px-6 text-base',
        icon: 'size-9',
      },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
)

export interface ButtonProps extends ComponentProps<'button'>, VariantProps<typeof variants> {
  asChild?: boolean
  /** Shows a spinner in place of the icon and blocks a second click; the label stays. */
  loading?: boolean
}

export function Button({ className, variant, size, asChild, loading, disabled, children, type = 'button', ...props }: ButtonProps) {
  if (asChild) {
    return (
      <Slot.Root className={cn(variants({ variant, size }), className)} {...props}>
        {children}
      </Slot.Root>
    )
  }
  return (
    <button
      className={cn(variants({ variant, size }), className)}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading && <Loader2 className="animate-spin" aria-hidden />}
      {children}
    </button>
  )
}
