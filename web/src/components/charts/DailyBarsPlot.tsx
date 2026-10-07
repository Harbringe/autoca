// The drawn bars of DailyBars: one bar per day. Loaded lazily by DailyBars.
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatDate } from '@/lib/format'

export interface DayPoint {
  date: string
  finished: number
}

const dayLabel = (iso: string) => String(Number(iso.slice(8, 10)))

function Tip({ active, payload }: { active?: boolean; payload?: { payload?: DayPoint }[] }) {
  const p = payload?.[0]?.payload
  if (!active || !p) return null
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-float">
      <div className="font-medium text-heading">{formatDate(p.date)}</div>
      <div className="num mt-1">{p.finished === 1 ? '1 entry finished' : `${p.finished} entries finished`}</div>
    </div>
  )
}

export default function DailyBarsPlot({ days }: { days: DayPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={days} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barCategoryGap="18%" accessibilityLayer={false}>
        <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
        <XAxis dataKey="date" tickFormatter={dayLabel} tickLine={false} axisLine={{ stroke: 'var(--chart-grid)' }} minTickGap={10} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} />
        <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={32} tickCount={4} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} />
        <Tooltip content={<Tip />} cursor={{ fill: 'var(--hover)' }} isAnimationActive={false} />
        <Bar dataKey="finished" name="Finished" fill="var(--chart-1)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  )
}
