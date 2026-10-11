import { Link } from '@tanstack/react-router'
import type { LucideIcon } from 'lucide-react'
import { AlertTriangle, CheckCircle2, OctagonAlert } from 'lucide-react'
import { percentages } from '@/lib/pct'
import { ChartTable } from './ChartTable'

export interface HealthPart {
  key: 'good' | 'watch' | 'bad'
  label: string
  count: number
  to?: string
  search?: Record<string, unknown>
}

const MARK: Record<HealthPart['key'], { color: string; icon: LucideIcon }> = {
  good: { color: 'var(--success)', icon: CheckCircle2 },
  watch: { color: 'var(--accent-foreground)', icon: AlertTriangle },
  bad: { color: 'var(--destructive)', icon: OctagonAlert },
}

const R = 40
const C = 2 * Math.PI * R

/**
 * A small ring for three parts, with the total in the middle and a labelled row for each part (icon, word, count, share).
 * Three parts is the most a ring is used for here; the words and icons carry the meaning, the ring only adds the shape.
 * Drawn in SVG with no chart library, so it costs nothing to load and does not animate.
 */
export function HealthDonut({ parts, centerLabel, ariaLabel, caption }: { parts: HealthPart[]; centerLabel: string; ariaLabel: string; caption: string }) {
  const total = parts.reduce((n, p) => n + p.count, 0)
  const shares = percentages(parts.map((p) => p.count))
  let offset = 0
  return (
    <div className="grid items-center gap-5 sm:grid-cols-[8.5rem_minmax(0,1fr)]">
      <div className="relative mx-auto" style={{ width: '8.5rem', height: '8.5rem' }}>
        <svg role="img" aria-label={ariaLabel} viewBox="0 0 100 100" className="size-full -rotate-90">
          <circle cx="50" cy="50" r={R} fill="none" stroke="var(--muted)" strokeWidth="12" />
          {total > 0 &&
            parts.map((p) => {
              if (p.count === 0) return null
              const len = (p.count / total) * C
              const gap = parts.filter((x) => x.count > 0).length > 1 ? 1.5 : 0
              const el = (
                <circle
                  key={p.key}
                  cx="50"
                  cy="50"
                  r={R}
                  fill="none"
                  stroke={MARK[p.key].color}
                  strokeWidth="12"
                  strokeDasharray={`${Math.max(len - gap, 0.5)} ${C}`}
                  strokeDashoffset={-offset}
                />
              )
              offset += len
              return el
            })}
        </svg>
        <div className="pointer-events-none absolute inset-0 grid place-content-center text-center" aria-hidden>
          <div className="num text-3xl font-semibold leading-8 text-heading">{total}</div>
          <div className="text-xs text-muted-foreground">{centerLabel}</div>
        </div>
      </div>
      <ul className="grid gap-0.5">
        {parts.map((p, i) => {
          const Icon = MARK[p.key].icon
          const body = (
            <>
              <Icon className="size-4 shrink-0" style={{ color: MARK[p.key].color }} aria-hidden />
              <span className="min-w-0 flex-1 truncate text-sm text-heading">{p.label}</span>
              <span className="num w-8 text-right text-sm font-semibold text-heading">{p.count}</span>
              <span className="num w-10 text-right text-xs text-muted-foreground">{shares[i]}%</span>
            </>
          )
          const box = 'flex min-h-10 items-center gap-2.5 rounded-md px-2 -mx-2'
          return (
            <li key={p.key}>
              {p.to && p.count > 0 ? (
                <Link to={p.to as never} search={p.search as never} className={`${box} hover:bg-hover`}>
                  {body}
                </Link>
              ) : (
                <div className={box}>{body}</div>
              )}
            </li>
          )
        })}
      </ul>
      <ChartTable caption={caption} columns={['Standing', 'Clients', 'Share']} rows={parts.map((p, i) => [p.label, p.count, `${shares[i]}%`])} />
    </div>
  )
}

/** A ring-shaped ghost while loading. */
export function HealthSkeleton() {
  return (
    <div className="grid items-center gap-5 sm:grid-cols-[8.5rem_minmax(0,1fr)]" aria-hidden>
      <span className="skeleton mx-auto block rounded-full" style={{ width: '8.5rem', height: '8.5rem' }} />
      <div className="grid gap-2">
        {Array.from({ length: 3 }, (_, i) => (
          <span key={i} className="skeleton block h-7 rounded" />
        ))}
      </div>
    </div>
  )
}
