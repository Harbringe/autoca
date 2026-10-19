import { Pause, Play } from 'lucide-react'
import { isApiError, messageOf } from '@/api/errors'
import { useAssistantPause } from '@/api/queries/clients'
import { GrowFill } from '@/components/charts/ProgressBar'
import { Button } from '@/components/ui/button'
import { Sparkles } from '@/components/ui/sparkles'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'
import { isPausedByPerson, isProcessing } from './queue'
import { useAssistantLine } from './useAssistant'

/**
 * One line on Bank statements and Review saying what the assistant is doing with this client's rows
 * (the top bar carries the same state and is the one announced to screen readers). Silent when the
 * assistant has nothing to say. While it reads, its four sparkles take turns to swell and fade; nothing else moves, so it costs
 * almost nothing on an old machine. A thin bar shows how far through a run it is.
 *
 * A person who may classify rows can Pause the assistant for this client while it reads, and Resume it after: paused, the
 * rows stay queued and nothing is sent to the model, until they say so.
 */
export function AssistantStrip({ clientId, className }: { clientId: string; className?: string }) {
  const { line, status } = useAssistantLine(clientId)
  const { can } = useSession()
  const pause = useAssistantPause(clientId)
  if (!line) return null
  const working = status.state === 'working' && status.reason === '' && status.total > 0
  const done = working ? Math.max(0, status.total - status.waiting) : 0
  const attention = status.reason === 'daily_limit' || status.reason === 'provider_down'
  const paused = isPausedByPerson(status)
  const canControl = can('transaction.classify')
  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border px-4 py-2.5 text-sm',
        attention ? 'border-accent-edge bg-accent text-accent-foreground' : 'border-info/30 bg-info-bg text-info',
        className,
      )}
    >
      <Sparkles working={working} className="size-6" />
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
          <GrowFill id="assistant-progress" percent={Math.max(4, Math.round((done / status.total) * 100))} className="rounded-full bg-info" />
        </span>
      )}
      {canControl && (paused || isProcessing(status)) && (
        <Button
          type="button"
          size="sm"
          variant={paused ? 'secondary' : 'ghost'}
          loading={pause.isPending}
          onClick={() => pause.mutate(!paused)}
          aria-label={paused ? 'Resume the assistant for this client' : 'Pause the assistant for this client'}
        >
          {paused ? <Play /> : <Pause />} {paused ? 'Resume' : 'Pause'}
        </Button>
      )}
      {pause.isError && (
        <span role="alert" className="basis-full text-sm text-destructive">
          {isApiError(pause.error) ? messageOf(pause.error) : 'Could not change the assistant. Try again.'}
        </span>
      )}
    </div>
  )
}
