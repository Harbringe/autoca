import { Link } from '@tanstack/react-router'
import { cn } from '@/lib/utils'
import { ChartTable } from './ChartTable'
import { segmentStyle, type SegmentTone } from './StackedBar'

export interface PipelineStage {
  key: string
  label: string
  count: number
  tone: SegmentTone
  to?: string
  params?: Record<string, string>
  search?: Record<string, unknown>
}

/**
 * Every stage as a big number over its own thin bar, and under them one thick bar made of the stages, in the order work
 * flows. The count is written once per stage, directly on it (no legend to decode); a stage with nothing in it is drawn
 * empty, not hidden, so the pipeline always has the same shape. Stages are links when they have somewhere to go.
 */
export function PipelineBar({ stages, unit, ariaLabel, caption }: { stages: PipelineStage[]; unit: string; ariaLabel: string; caption: string }) {
  const total = stages.reduce((n, s) => n + s.count, 0)
  const top = Math.max(1, ...stages.map((s) => s.count))
  return (
    <div className="@container grid gap-3">
      <ul className="grid grid-cols-2 gap-x-4 gap-y-3 @sm:grid-cols-3 @3xl:grid-cols-6">
        {stages.map((s) => {
          const body = (
            <>
              <span className="num block text-[28px] font-semibold leading-8 text-heading">{s.count}</span>
              <span className="mt-0.5 flex items-start gap-1.5 text-xs leading-tight text-muted-foreground">
                <span className="mt-1 size-2 shrink-0 rounded-full" style={segmentStyle(s.tone)} aria-hidden />
                <span>{s.label}</span>
              </span>
              <span className="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                <span className="block h-full rounded-full" style={{ ...segmentStyle(s.tone), width: `${(s.count / top) * 100}%` }} />
              </span>
            </>
          )
          const box = 'block min-h-11 min-w-0 rounded-md px-1.5 -mx-1.5 py-1'
          return (
            <li key={s.key} className="min-w-0">
              {s.to && s.count > 0 ? (
                <Link to={s.to as never} params={s.params as never} search={s.search as never} className={cn(box, 'hover:bg-hover')}>
                  {body}
                </Link>
              ) : (
                <div className={box}>{body}</div>
              )}
            </li>
          )
        })}
      </ul>
      <div role="img" aria-label={ariaLabel} className="flex h-3.5 w-full gap-0.5 overflow-hidden rounded-full bg-muted ring-1 ring-inset ring-[var(--faint)]">
        {total > 0 &&
          stages.map((s) =>
            s.count > 0 ? <span key={s.key} title={`${s.label}: ${s.count} ${unit}`} className="block h-full" style={{ ...segmentStyle(s.tone), width: `${(s.count / total) * 100}%` }} /> : null,
          )}
      </div>
      <ChartTable caption={caption} columns={['Stage', unit]} rows={stages.map((s) => [s.label, s.count])} />
    </div>
  )
}

/** The pipeline's shape while it loads. */
export function PipelineSkeleton() {
  return (
    <div className="grid gap-3" aria-hidden>
      <div className="grid grid-cols-3 gap-4 sm:grid-cols-6">
        {Array.from({ length: 6 }, (_, i) => (
          <span key={i} className="skeleton block h-14 rounded" />
        ))}
      </div>
      <span className="skeleton block h-3.5 rounded-full" />
    </div>
  )
}
