// The drawn bars of MonthBars. Only this file imports the chart library for it; MonthBars loads it lazily.
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatPaise } from '@/lib/format'
import { axisMoney, monthLong, monthShort } from '@/lib/chartFormat'

export interface MonthPoint {
  month: string
  income_paise: number
  expense_paise: number
}

function Tip({ active, payload }: { active?: boolean; payload?: { payload?: MonthPoint }[] }) {
  const p = payload?.[0]?.payload
  if (!active || !p) return null
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-float">
      <div className="font-medium text-heading">{monthLong(p.month)}</div>
      <div className="num mt-1">Income {formatPaise(p.income_paise)}</div>
      <div className="num">Expense {formatPaise(p.expense_paise)}</div>
    </div>
  )
}

export default function MonthBarsChart({ trend }: { trend: MonthPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={trend} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barGap={2} barCategoryGap="22%" accessibilityLayer={false}>
        <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
        <XAxis dataKey="month" tickFormatter={monthShort} tickLine={false} axisLine={{ stroke: 'var(--chart-grid)' }} interval={0} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} />
        <YAxis tickFormatter={axisMoney} tickLine={false} axisLine={false} width={64} tickCount={5} tick={{ fill: 'var(--muted-foreground)', fontSize: 12 }} />
        <Tooltip content={<Tip />} cursor={{ fill: 'var(--hover)' }} isAnimationActive={false} />
        <Bar dataKey="income_paise" name="Income" fill="var(--chart-1)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
        <Bar dataKey="expense_paise" name="Expense" fill="var(--chart-2)" radius={[2, 2, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  )
}
