import { cn } from '@/lib/utils'

// Four pointed stars of different sizes, the shape of the sparkle used for the assistant. Each is [centre x, centre y, radius].
const STARS: [number, number, number][] = [
  [64, 54, 30],
  [26, 27, 17],
  [32, 76, 12],
  [82, 26, 8],
]

/** A four-pointed star with pinched sides, drawn about its own centre. */
function star(cx: number, cy: number, r: number): string {
  const w = r * 0.2
  return `M${cx} ${cy - r}C${cx + w} ${cy - w} ${cx + w} ${cy - w} ${cx + r} ${cy}C${cx + w} ${cy + w} ${cx + w} ${cy + w} ${cx} ${cy + r}C${cx - w} ${cy + w} ${cx - w} ${cy + w} ${cx - r} ${cy}C${cx - w} ${cy - w} ${cx - w} ${cy - w} ${cx} ${cy - r}Z`
}

/**
 * The assistant's mark: four stars that take turns to swell and fade while it works, and sit still otherwise.
 * It moves only transform and opacity of a few tiny shapes, so it costs almost nothing on an old machine, and it stops
 * under reduced motion. Takes its colour from the text around it.
 */
export function Sparkles({ working = false, className }: { working?: boolean; className?: string }) {
  return (
    <svg viewBox="0 0 100 100" aria-hidden className={cn('size-5 shrink-0', className)} fill="currentColor">
      {STARS.map(([x, y, r], i) => (
        <path
          key={i}
          d={star(x, y, r)}
          className={cn(working && 'motion-safe:animate-[sparkle_1.8s_ease-in-out_infinite] [transform-box:fill-box] [transform-origin:center]')}
          style={working ? { animationDelay: `${i * 0.45}s` } : undefined}
        />
      ))}
    </svg>
  )
}
