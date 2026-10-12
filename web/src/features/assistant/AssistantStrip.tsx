import { Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAssistantLine } from './useAssistant'

/**
 * One line on Bank statements and Review saying what the assistant is doing with this client's rows
 * (the top bar carries the same state and is the one announced to screen readers). Silent when the
 * assistant has nothing to say. While it reads, its icon gently turns; nothing else moves, so it costs
 * almost nothing on an old machine. A thin bar shows how far through a run it is.
 */
export function AssistantStrip({ clientId, className }: { clientId: string; className?: string }) {
  const { line, status } = useAssistantLine(clientId)
  if (!line) return null
  const working = status.state === 'working' && status.reason === '' && status.total > 0
  const done = working ? Math.max(0, status.total - status.waiting) : 0
  const attention = status.reason === 'daily_limit' || status.reason === 'provider_down'
  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border px-4 py-2.5 text-sm',
        attention ? 'border-accent-edge bg-accent text-accent-foreground' : 'border-info/30 bg-info-bg text-info',
        className,
      )}
    >
      <Sparkles className={cn('size-4 shrink-0', working && 'motion-safe:animate-[twinkle_1.6s_ease-in-out_infinite]')} aria-hidden />
      <span className="min-w-0 flex-1">{line}</span>
      {working && (
        <span
          role="progressbar"
          aria-label="Rows the assistant has read"
          aria-valuemin={0}
          aria-valuemax={status.total}
          aria-valuenow={done}
          className="h-1.5 w-32 overflow-hidden rounded-full bg-card/70 max-sm:w-full"
        >
          <span className="block h-full rounded-full bg-info" style={{ width: `${Math.max(4, Math.round((done / status.total) * 100))}%` }} />
        </span>
      )}
    </div>
  )
}
