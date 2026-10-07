// "What should I do next?": one line per thing to do, each with a button that goes to exactly where it
// is done. The button is the tab stop, so a keyboard user walks the list with Tab and Enter.

import { Link } from '@tanstack/react-router'
import { ArrowRight } from 'lucide-react'
import type { Action } from '@/lib/dashboard'
import { Button } from '@/components/ui/button'

export function ActionList({ items, more, moreTo }: { items: Action[]; more?: number; moreTo?: string }) {
  return (
    <div>
      <ol className="divide-y">
        {items.map((a, i) => (
          <li key={a.key} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3 first:pt-0">
            <span className="num grid size-6 shrink-0 place-items-center rounded-full bg-muted text-xs font-semibold text-muted-foreground" aria-hidden>
              {i + 1}
            </span>
            <div className="min-w-0 flex-1 basis-52">
              <div className="truncate text-sm font-semibold text-heading" title={a.client}>
                {a.client}
              </div>
              <div className="text-[13px] text-muted-foreground">{a.title}</div>
              {a.detail && <div className="text-xs text-accent-foreground">Late: {a.detail}</div>}
            </div>
            <Button asChild size="sm" variant={i === 0 ? 'primary' : 'secondary'} className="max-sm:min-h-11 max-sm:w-full">
              <Link to={a.target.to as never} params={{ clientId: a.clientId } as never} search={a.target.search as never} aria-label={`${a.cta}: ${a.title}, ${a.client}`}>
                {a.cta} <ArrowRight />
              </Link>
            </Button>
          </li>
        ))}
      </ol>
      {!!more && more > 0 && (
        <p className="mt-3 border-t pt-3 text-[13px] text-muted-foreground">
          And {more} more.{' '}
          {moreTo && (
            <Link to={moreTo as never} className="text-link underline underline-offset-2">
              See them all
            </Link>
          )}
        </p>
      )}
    </div>
  )
}
