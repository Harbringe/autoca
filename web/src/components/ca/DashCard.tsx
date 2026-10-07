// One question, one answer, on a card. The title is a plain question or noun phrase and is the card's
// heading, so a screen reader can jump card to card. Each card owns its four states: while its own query
// loads it shows a skeleton of its height, when it fails it says so with a way to retry, when there is
// nothing yet it says what to do. One failing card never blanks the page, and a card the person's role
// may not read (a 403) renders nothing rather than an error they cannot act on.

import { Link } from '@tanstack/react-router'
import { useId, type ReactNode } from 'react'
import { isApiError } from '@/api/errors'
import { ErrorState } from '@/components/ca/Page'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils'

export type CardState = 'ready' | 'loading' | 'error' | 'empty'

export interface DashCardProps {
  title: string
  /** One short line under the title: what the card counts, or what time it covers. */
  hint?: ReactNode
  /** The screen that lists exactly what this card summarises. */
  to?: string
  params?: Record<string, string>
  search?: Record<string, unknown>
  seeAll?: string
  state?: CardState
  /** What to show when there is nothing yet; written per card, never a blank chart. */
  empty?: ReactNode
  error?: unknown
  onRetry?: () => void
  /** Height of the skeleton while loading, as a Tailwind class. */
  skeleton?: string
  className?: string
  children?: ReactNode
}

export function DashCard({
  title,
  hint,
  to,
  params,
  search,
  seeAll = 'See all',
  state = 'ready',
  empty,
  error,
  onRetry,
  skeleton = 'h-32',
  className,
  children,
}: DashCardProps) {
  const id = useId()
  if (state === 'error' && isApiError(error) && error.status === 403) return null
  return (
    <Card className={cn('h-full min-w-0 p-5', className)} role="region" aria-labelledby={id} aria-busy={state === 'loading' || undefined}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id={id} className="text-[15px] font-semibold leading-snug text-heading">
            {title}
          </h2>
          {hint && <p className="mt-0.5 text-[13px] text-muted-foreground">{hint}</p>}
        </div>
        {to && state === 'ready' && (
          <Link
            to={to as never}
            params={params as never}
            search={search as never}
            aria-label={`${seeAll}: ${title}`}
            className="no-print -my-2 inline-flex min-h-11 shrink-0 items-center text-[13px] text-link underline underline-offset-2 sm:min-h-8"
          >
            {seeAll}
          </Link>
        )}
      </div>
      <div className="mt-3">
        {state === 'loading' ? (
          <div className={cn('skeleton', skeleton)}>
            <span className="sr-only">Loading: {title}</span>
          </div>
        ) : state === 'error' ? (
          <ErrorState error={error} retry={onRetry} />
        ) : state === 'empty' ? (
          <p className="text-sm text-muted-foreground">{empty}</p>
        ) : (
          children
        )}
      </div>
    </Card>
  )
}
