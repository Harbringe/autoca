import { AlertTriangle } from 'lucide-react'
import { createContext, useContext, type ReactNode } from 'react'
import { errorTitle, isApiError, messageOf } from '@/api/errors'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** Inside a page that already has its own h1 (Settings), the screen's title is an h2. */
export const HeadingLevel = createContext<1 | 2>(1)

export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  className?: string
}) {
  const level = useContext(HeadingLevel)
  return (
    <div className={cn('mb-5 flex flex-wrap items-start justify-between gap-3', className)}>
      <div className="min-w-0">
        {level === 1 ? (
          <h1 className="text-[26px] leading-8 xl:text-[28px] xl:leading-[34px]">{title}</h1>
        ) : (
          <h2 className="text-xl font-semibold leading-7 text-heading">{title}</h2>
        )}
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="grid justify-items-center gap-2 rounded-lg border border-dashed p-10 text-center">
      <h2 className="text-[15px] font-semibold text-heading">{title}</h2>
      {children && <p className="max-w-md text-sm text-muted-foreground">{children}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

/** Whether asking again could possibly give a different answer. A refusal will not. */
function retryable(error: unknown): boolean {
  if (!isApiError(error)) return true
  return error.status >= 500 || error.status === 408 || error.status === 429
}

/** A failed load, in the server's own words, with a way to try again only when trying again can help. */
export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const notFound = isApiError(error) && error.status === 404
  // The server's 404 wording is a framework's ("No Client matches the given query"). It is also the
  // answer for "you are not on this client", so it is not said as if the thing were missing.
  const title = notFound ? 'Not available' : isApiError(error) ? errorTitle(error) : undefined
  const message = notFound ? 'This does not exist, or you are not on it. Ask your senior CA if you should be.' : messageOf(error)
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-destructive/40 bg-destructive-bg p-4">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
      <div className="min-w-0 flex-1 text-sm">
        {title && <div className="font-semibold">{title}</div>}
        <div>{message}</div>
      </div>
      {retry && retryable(error) && (
        <Button variant="outline" size="sm" onClick={retry}>
          Try again
        </Button>
      )}
    </div>
  )
}
