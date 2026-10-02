import { Check, CircleAlert, CircleDot } from 'lucide-react'
import { plural } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * Where a set of rows stands: posted, ready to post, needs a ledger. The bar is one image with a
 * text alternative, and the legend beside it says the same in words with a shape per state, so
 * colour is never the only signal. Widths are shares of the total; a zero share takes no room.
 */
export function StandingBar({ posted, ready, needs, className }: { posted: number; ready: number; needs: number; className?: string }) {
  const total = posted + ready + needs
  const label = `${posted} posted, ${ready} ready to post, ${needs} ${needs === 1 ? 'needs' : 'need'} a ledger`
  const share = (n: number) => (total ? `${(n / total) * 100}%` : '0%')
  return (
    <div className={cn('grid gap-2', className)}>
      <div role="img" aria-label={label} className="flex h-2.5 overflow-hidden rounded-full bg-muted">
        <div className="bg-success" style={{ width: share(posted) }} />
        <div className="bg-info" style={{ width: share(ready) }} />
        <div className="bg-accent-foreground" style={{ width: share(needs) }} />
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[13px]" aria-hidden>
        <li className="flex items-center gap-1.5 text-success">
          <Check className="size-3.5" /> <span className="num font-semibold">{posted}</span> <span className="text-muted-foreground">posted</span>
        </li>
        <li className="flex items-center gap-1.5 text-info">
          <CircleDot className="size-3.5" /> <span className="num font-semibold">{ready}</span> <span className="text-muted-foreground">ready to post</span>
        </li>
        <li className="flex items-center gap-1.5 text-accent-foreground">
          <CircleAlert className="size-3.5" /> <span className="num font-semibold">{needs}</span> <span className="text-muted-foreground">{needs === 1 ? 'needs' : 'need'} a ledger</span>
        </li>
        <li className="ml-auto text-muted-foreground">{plural(total, 'row')} in all</li>
      </ul>
    </div>
  )
}
