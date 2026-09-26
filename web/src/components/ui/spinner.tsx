import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

export function Spinner({ label, className }: { label?: string; className?: string }) {
  return (
    <div role="status" className={cn('flex items-center justify-center gap-2 p-8 text-sm text-muted-foreground', className)}>
      <Loader2 className="size-4 animate-spin" aria-hidden />
      <span>{label ?? 'Loading…'}</span>
    </div>
  )
}
