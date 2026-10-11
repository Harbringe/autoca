/**
 * A tiny line of one series, for a headline figure. It says the shape only: no axis, so the figure beside it carries the
 * number. Drawn only from a real series of two or more points; callers show nothing otherwise rather than a flat fake.
 * `zero` keeps the baseline at zero (use it for counts and money) so a small change does not look like a cliff.
 */
export function Sparkline({
  values,
  ariaLabel,
  zero = true,
  width = 96,
  height = 28,
}: {
  values: number[]
  ariaLabel: string
  zero?: boolean
  width?: number
  height?: number
}) {
  if (values.length < 2) return null
  const lo = zero ? Math.min(0, ...values) : Math.min(...values)
  const hi = Math.max(...values, lo + 1)
  const pad = 3
  const x = (i: number) => pad + (i * (width - pad * 2)) / (values.length - 1)
  const y = (v: number) => height - pad - ((v - lo) / (hi - lo)) * (height - pad * 2)
  const points = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const last = values.length - 1
  return (
    <svg role="img" aria-label={ariaLabel} viewBox={`0 0 ${width} ${height}`} width={width} height={height} className="shrink-0 overflow-visible">
      {zero && lo < 0 && <line x1={pad} x2={width - pad} y1={y(0)} y2={y(0)} stroke="var(--chart-grid)" strokeWidth={1} />}
      <polyline points={points} fill="none" stroke="var(--chart-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={x(last)} cy={y(values[last]!)} r={2.5} fill="var(--chart-1)" stroke="var(--card)" strokeWidth={1.5} />
    </svg>
  )
}
