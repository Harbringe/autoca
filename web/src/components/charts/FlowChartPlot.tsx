// The drawn weekly chart: bars for rows received, a line for entries finished. Loaded lazily by FlowChart.
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatDate } from '@/lib/format'
import { weekLabel } from '@/lib/flow'

export interface WeekPoint {
  week_start: string
  received: number
  finished: number
  /** True for a first or last week that is only partly inside the period. */
  partial: boolean
}

function Tip({ active, payload }: { active?: boolean; payload?: { payload?: WeekPoint }[] }) {
  const p = payload?.[0]?.payload
  if (!active || !p) return null
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-float">
      <div className="font-medium text-heading">Week of {formatDate(p.week_start)}</div>
      {p.partial && <div className="text-muted-foreground">Part of this week is outside the period</div>}
      <div className="num mt-1">Received {p.received} rows</div>
      <div className="num">Finished {p.finished} entries</div>
    </div>
  )
}

export default function FlowChartPlot({ weeks }: { weeks: WeekPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={weeks} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} accessibilityLayer={false}>
        <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
        <XAxis dataKey="week_start" tickFormatter={weekLabel} tickLine={false} axisLine={{ stroke: 'var(--chart-grid)' }} minTickGap={12} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} />
        <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={40} tickCount={5} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} />
        <Tooltip content={<Tip />} cursor={{ fill: 'var(--hover)' }} isAnimationActive={false} />
        <Bar dataKey="received" name="Received" fill="var(--chart-muted)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
        <Line dataKey="finished" name="Finished" type="monotone" stroke="var(--chart-1)" strokeWidth={2.5} dot={{ r: 3, fill: 'var(--chart-1)', stroke: 'var(--card)' }} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
