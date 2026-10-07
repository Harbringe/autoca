// "How complete are my books?": one wide card. The share is whole months with a statement out of the months
// that have fully passed; the strip shows each month of the year; the button is the next step, so the page
// answers "what do I do now" without reading anything else.

import { Check, Minus } from 'lucide-react'
import type { ReactNode } from 'react'
import { DashCard } from '@/components/ca/DashCard'
import { ProgressBar } from '@/components/charts/ProgressBar'
import { formatDate, fyLabel, plural } from '@/lib/format'
import { pct } from '@/lib/pct'
import { cn } from '@/lib/utils'
import { coverageText, type BooksProgress as Progress, type MonthCover } from './standing'

const LABEL = { full: 'a statement covers this month', partial: 'a statement covers part of this month', none: 'no statement' } as const

export function BooksProgressCard({
  fy,
  months,
  progress,
  hasStatements,
  nextTitle,
  nextAction,
  signedOffThrough,
  upload,
}: {
  fy: number
  months: MonthCover[]
  progress: Progress
  hasStatements: boolean
  /** The first step not yet done, or null when every step is done. */
  nextTitle: string | null
  nextAction: ReactNode
  signedOffThrough: string | null | undefined
  upload: ReactNode
}) {
  const share = pct(progress.done, progress.due)
  const word = progress.due === 0 ? 'The year has only just begun' : `${share}% done`
  return (
    <DashCard title="How complete are my books?" hint={<span className="num">Financial year {fyLabel(fy)}, April to March</span>}>
      {!hasStatements ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-prose text-sm text-muted-foreground">No statements have been uploaded yet. Upload the first bank statement to begin.</p>
          {upload}
        </div>
      ) : (
        <div className="grid gap-4">
          <div className="grid items-end gap-x-6 gap-y-2 sm:grid-cols-[auto_minmax(0,1fr)]">
            <div>
              <div className="num text-[28px] font-semibold leading-8 text-heading">{word}</div>
              {progress.due > 0 && (
                <div className="mt-0.5 text-[13px] text-muted-foreground">
                  {progress.done} of {plural(progress.due, 'month')} covered by a statement
                  {progress.due - progress.done > 0 ? `, ${progress.due - progress.done} still to do` : ''}
                </div>
              )}
            </div>
            <ProgressBar value={progress.done} max={Math.max(progress.due, 1)} label={`${progress.done} of ${plural(progress.due, 'month')} covered by a statement`} className="h-2.5 sm:mb-2" />
          </div>

          <ol className="grid grid-cols-6 gap-2 sm:grid-cols-12" aria-hidden>
            {months.map((m, i) => {
              const later = i >= progress.due
              return (
                <li key={m.start} className="grid justify-items-center gap-1" title={`${m.label}: ${later && m.coverage === 'none' ? 'not due yet' : LABEL[m.coverage]}`}>
                  <span
                    className={cn(
                      'grid h-9 w-full place-items-center rounded-md border',
                      m.coverage === 'full' && 'border-primary bg-primary text-primary-foreground',
                      m.coverage === 'partial' && 'border-primary bg-[linear-gradient(90deg,var(--primary)_50%,transparent_50%)]',
                      m.coverage === 'none' && !later && 'border-input text-muted-foreground',
                      m.coverage === 'none' && later && 'border-dashed border-border text-faint',
                    )}
                  >
                    {m.coverage === 'full' ? <Check className="size-4" /> : m.coverage === 'none' && !later ? <Minus className="size-4" /> : null}
                  </span>
                  <span className={cn('text-xs', later && m.coverage === 'none' ? 'text-faint' : 'text-muted-foreground')}>{m.label}</span>
                </li>
              )
            })}
          </ol>
          <p className="text-[13px] text-muted-foreground">
            {progress.due > 0 ? coverageText(months.slice(0, progress.due)) : 'No month has fully passed yet.'}
            {progress.due < 12 && ' Later months are not due yet.'}
          </p>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
            {nextTitle ? (
              <>
                <div className="min-w-0">
                  <div className="text-xs text-muted-foreground">Next step</div>
                  <div className="text-sm font-semibold text-heading">{nextTitle}</div>
                </div>
                {nextAction && <div className="max-sm:w-full [&>*]:max-sm:w-full">{nextAction}</div>}
              </>
            ) : (
              <div className="text-sm text-heading">Every step is done{signedOffThrough ? `. The books are signed off to ${formatDate(signedOffThrough)}.` : '.'}</div>
            )}
          </div>
        </div>
      )}
    </DashCard>
  )
}
