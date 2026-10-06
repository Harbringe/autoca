import { Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAssistantLine } from './useAssistant'

/**
 * One line on Bank statements and Review saying what the assistant is doing with this client's rows
 * (the top bar carries the same state and is the one announced to screen readers). Silent when the
 * assistant has nothing to say. A bar shows how far through a run it is.
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
        'flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border px-3 py-2 text-[13px]',
        attention ? 'border-accent-edge bg-accent text-accent-foreground' : 'bg-info-bg text-info',
        className,
      )}
    >
      <Sparkles className={cn('size-4 shrink-0', !attention && 'motion-safe:animate-pulse')} aria-hidden />
      <span className="min-w-0 flex-1">{line}</span>
      {working && (
        <progress
          value={done}
          max={status.total}
          aria-label="Rows the assistant has read"
          className="h-1.5 w-32 max-sm:w-full [&::-moz-progress-bar]:bg-info [&::-webkit-progress-bar]:rounded-full [&::-webkit-progress-bar]:bg-card [&::-webkit-progress-value]:rounded-full [&::-webkit-progress-value]:bg-info"
        />
      )}
    </div>
  )
}
