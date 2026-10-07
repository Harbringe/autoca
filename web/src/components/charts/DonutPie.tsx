// The drawn ring of a DonutLegend. The only file that imports the chart library for it, loaded lazily
// by DonutLegend, so screens that show no chart never download it.
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'

export interface Slice {
  key: string
  label: string
  count: number
  percent: number
  /** A CSS colour, normally a `var(--chart-…)` token so the theme decides. */
  color: string
}

function Tip({ active, payload }: { active?: boolean; payload?: { payload?: Slice }[] }) {
  const slice = payload?.[0]?.payload
  if (!active || !slice) return null
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-float">
      <div className="font-medium text-heading">{slice.label}</div>
      <div className="num mt-0.5">
        {slice.count} ({slice.percent}%)
      </div>
    </div>
  )
}

export default function DonutPie({ slices, total }: { slices: Slice[]; total: number }) {
  const shown = slices.filter((s) => s.count > 0)
  const data = total > 0 ? shown : [{ key: 'none', label: 'None', count: 1, percent: 0, color: 'var(--chart-grid)' }]
  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart accessibilityLayer={false}>
        {total > 0 && <Tooltip content={<Tip />} isAnimationActive={false} />}
        <Pie
          data={data}
          dataKey="count"
          nameKey="label"
          innerRadius="64%"
          outerRadius="100%"
          paddingAngle={data.length > 1 ? 2 : 0}
          stroke="var(--card)"
          strokeWidth={2}
          startAngle={90}
          endAngle={-270}
          isAnimationActive={false}
        >
          {data.map((s) => (
            <Cell key={s.key} fill={s.color} />
          ))}
        </Pie>
      </PieChart>
    </ResponsiveContainer>
  )
}
