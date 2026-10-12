import { Check, CircleAlert, CircleDot } from 'lucide-react'
import { plural } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * Where a set of rows stands: posted, ready to post, needs a ledger. The bar is one image with a
 * text alternative, and the legend beside it says the same in words with a shape per state, so
 * colour is never the only signal. Widths are shares of the total; a zero share takes no room.
 */
export function StandingBar({ posted, ready, needs, className, roomy }: { posted: number; ready: number; needs: number; className?: string; roomy?: boolean }) {
  const total = posted + ready + needs
  const label = `${posted} posted, ${ready} ready to post, ${needs} ${needs === 1 ? 'needs' : 'need'} a ledger`
  const share = (n: number) => (total ? `${(n / total) * 100}%` : '0%')
  return (
    <div className={cn('grid gap-2', className)}>
      <div role="img" aria-label={label} className={cn('flex overflow-hidden rounded-full bg-muted', roomy ? 'h-3 gap-0.5 bg-transparent' : 'h-2.5')}>
        <div className={cn('bg-success', roomy && 'rounded-full')} style={{ width: share(posted) }} />
        <div className={cn('bg-info', roomy && 'rounded-full')} style={{ width: share(ready) }} />
        <div className={cn('bg-accent-foreground', roomy && 'rounded-full')} style={{ width: share(needs) }} />
      </div>
      <ul className={cn('flex flex-wrap gap-x-5 gap-y-1', roomy ? 'mt-1 text-[15px]' : 'text-[13px]')} aria-hidden>
        <li className="flex items-center gap-1.5 text-success">
          {roomy ? <span className="size-3 rounded-[3px] bg-success" /> : <Check className="size-3.5" />} <span className={cn('num font-semibold', roomy && 'text-heading')}>{posted}</span> <span className="text-muted-foreground">posted</span>
        </li>
        <li className="flex items-center gap-1.5 text-info">
          {roomy ? <span className="size-3 rounded-[3px] bg-info" /> : <CircleDot className="size-3.5" />} <span className={cn('num font-semibold', roomy && 'text-heading')}>{ready}</span> <span className="text-muted-foreground">ready to post</span>
        </li>
        <li className="flex items-center gap-1.5 text-accent-foreground">
          {roomy ? <span className="size-3 rounded-[3px] bg-accent-foreground" /> : <CircleAlert className="size-3.5" />} <span className={cn('num font-semibold', roomy && 'text-heading')}>{needs}</span> <span className="text-muted-foreground">{needs === 1 ? 'needs' : 'need'} a ledger</span>
        </li>
        {!roomy && <li className="ml-auto text-muted-foreground">{plural(total, 'row')} in all</li>}
      </ul>
    </div>
  )
}
