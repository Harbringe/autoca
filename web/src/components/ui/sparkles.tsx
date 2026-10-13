import { cn } from '@/lib/utils'

/**
 * The assistant's mark: four small rounded squares in a two-by-two grid that take turns to swell and fade while it works, and sit
 * quietly at half strength otherwise. Only transform and opacity of four tiny blocks move, so it costs almost nothing on an old
 * machine, and under reduced motion it holds still. It is sized by its class (`size-4`, `size-6`) and takes the assistant's teal.
 */
export function Sparkles({ working = false, className }: { working?: boolean; className?: string }) {
  return (
    <span aria-hidden className={cn('inline-grid size-5 shrink-0 grid-cols-2 grid-rows-2 gap-[2px] p-[2px] text-primary', className)}>
      {[0, 1, 2, 3].map((i) => (
        <i
          key={i}
          className={cn(
            'block rounded-[2px] bg-current',
            working ? 'motion-safe:animate-[spark-swell_1.4s_ease-in-out_infinite] motion-reduce:opacity-80' : 'opacity-50',
          )}
          style={working ? { animationDelay: `${i * 0.2}s` } : undefined}
        />
      ))}
    </span>
  )
}
