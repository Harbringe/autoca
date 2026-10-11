import { formatDate } from '@/lib/format'
import { isoOf } from '@/lib/period'
import { cn } from '@/lib/utils'
import { ChartTable } from './ChartTable'

export interface DueItem {
  date: string
  label: string
  clients: string[]
}

const DAY = 86_400_000
const dayIndex = (iso: string, today: Date) => Math.round((Date.parse(`${iso}T00:00:00Z`) - Date.UTC(today.getFullYear(), today.getMonth(), today.getDate())) / DAY)

/**
 * The next `days` days as a line with a marker for each date that something falls due. Same-day items share one marker. Tick
 * labels are dates (DD-MM-YYYY); a TDS deposit is a dot and a sealing date a diamond, so the kind survives greyscale.
 * The list under the line is the drill-down: what falls due on that date and for how many clients.
 */
export function DueTimeline({ items, today, days = 30 }: { items: DueItem[]; today: Date; days?: number }) {
  const byDay = new Map<number, DueItem[]>()
  for (const it of items) {
    const i = dayIndex(it.date, today)
    if (i < 0 || i > days) continue
    byDay.set(i, [...(byDay.get(i) ?? []), it])
  }
  const ticks = [0, 7, 14, 21, days]
  const date = (i: number) => {
    const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() + i)
    return formatDate(isoOf(d))
  }
  const shape = (label: string) => (/seal/i.test(label) ? 'rotate-45 rounded-[2px]' : 'rounded-full')
  const summary = items.length === 0 ? `Nothing falls due in the next ${days} days.` : `${items.length} due dates in the next ${days} days.`
  return (
    <div>
      <div role="img" aria-label={summary} className="relative mx-2 h-9">
        <span className="absolute inset-x-0 top-1/2 h-px bg-[var(--faint)]" aria-hidden />
        {ticks.map((t) => (
          <span key={t} className="absolute top-1/2 h-2 w-px -translate-y-1/2 bg-[var(--faint)]" style={{ left: `${(t / days) * 100}%` }} aria-hidden />
        ))}
        {[...byDay.entries()].map(([i, list]) => (
          <span
            key={i}
            title={`${date(i)}: ${list.map((l) => `${l.label} (${l.clients.length})`).join(', ')}`}
            className={cn(
              'absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 border-2 border-card',
              shape(list[0]!.label),
              list.some((l) => /seal/i.test(l.label)) && !list.some((l) => !/seal/i.test(l.label)) ? 'bg-[var(--chart-1)]' : 'bg-[var(--accent-foreground)]',
            )}
            style={{ left: `${(i / days) * 100}%` }}
          />
        ))}
      </div>
      <div className="num relative mx-2 mb-1 flex h-4 justify-between text-xs text-muted-foreground" aria-hidden>
        {ticks.map((t) => (
          <span key={t}>{t === 0 ? 'Today' : date(t).slice(0, 5)}</span>
        ))}
      </div>
      {byDay.size === 0 ? (
        <p className="text-sm text-muted-foreground">Nothing falls due in the next {days} days.</p>
      ) : (
        <ul className="divide-y text-sm">
          {[...byDay.entries()]
            .sort((a, b) => a[0] - b[0])
            .flatMap(([, list]) => list)
            .map((l) => (
              <li key={`${l.date}-${l.label}`} className="flex items-baseline justify-between gap-3 py-1.5" title={l.clients.join(', ')}>
                <span className="min-w-0 truncate">
                  <span className="num mr-2 text-muted-foreground">{formatDate(l.date)}</span>
                  <strong className="font-medium text-heading">{l.label}</strong>
                </span>
                <span className="num shrink-0 text-muted-foreground">{l.clients.length === 1 ? '1 client' : `${l.clients.length} clients`}</span>
              </li>
            ))}
        </ul>
      )}
      <ChartTable caption="Due dates in the next 30 days" columns={['Date', 'What', 'Clients']} rows={items.map((l) => [formatDate(l.date), l.label, l.clients.length])} />
    </div>
  )
}
