import { Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAssistantLine } from './useAssistant'

/**
 * One line on Bank statements and Review saying what the assistant is doing with this client's rows
 * (the top bar carries the same state and is the one announced to screen readers). Silent when the
 * assistant has nothing to say.
 *
 * While it is reading it is alive: a soft light sweeps across the strip, the icon pulses a ring and twinkles,
 * and the bar fills with moving stripes as each row is read. When it is waiting or has stopped, all of it is still.
 */
export function AssistantStrip({ clientId, className }: { clientId: string; className?: string }) {
  const { line, status } = useAssistantLine(clientId)
  if (!line) return null
  const working = status.state === 'working' && status.reason === '' && status.total > 0
  const done = working ? Math.max(0, status.total - status.waiting) : 0
  const attention = status.reason === 'daily_limit' || status.reason === 'provider_down'
  const share = working ? Math.min(100, Math.max(4, Math.round((done / status.total) * 100))) : 0
  return (
    <div
      className={cn(
        'relative flex flex-wrap items-center gap-x-4 gap-y-2 overflow-hidden rounded-xl border px-4 py-3 text-sm',
        attention ? 'border-accent-edge bg-accent text-accent-foreground' : 'border-info/30 bg-info-bg text-info',
        className,
      )}
    >
      {working && (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-y-0 left-0 w-1/4 bg-gradient-to-r from-transparent via-info/15 to-transparent motion-safe:animate-[sweep_2.8s_ease-in-out_infinite]"
        />
      )}
      <span className="relative grid size-9 shrink-0 place-items-center rounded-full bg-current/10" aria-hidden>
        {working && <span className="absolute inset-0 rounded-full border border-current motion-safe:animate-[ring_1.8s_ease-out_infinite]" />}
        <Sparkles className={cn('size-4', working && 'motion-safe:animate-[twinkle_1.8s_ease-in-out_infinite]')} />
      </span>
      <span className="relative min-w-0 flex-1">{line}</span>
      {working && (
        <span className="relative flex items-center gap-3 max-sm:w-full">
          <span
            role="progressbar"
            aria-label="Rows the assistant has read"
            aria-valuemin={0}
            aria-valuemax={status.total}
            aria-valuenow={done}
            className="h-2 w-40 overflow-hidden rounded-full bg-card/70 max-sm:w-full"
          >
            <span
              className="block h-full rounded-full bg-info transition-[width] duration-700 ease-out motion-safe:animate-[stripes_900ms_linear_infinite]"
              style={{
                width: `${share}%`,
                backgroundImage: 'repeating-linear-gradient(135deg, rgb(255 255 255 / 0.28) 0 7px, transparent 7px 14px)',
                backgroundSize: '28px 28px',
              }}
            />
          </span>
          <span className="num text-[13px] font-semibold tabular-nums">
            {done} of {status.total}
          </span>
        </span>
      )}
    </div>
  )
}
