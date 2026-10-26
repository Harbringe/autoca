// A link that is shown once: readonly, selectable, with a button that copies it.

import { Copy } from 'lucide-react'
import { toast } from '@/lib/toast'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export function copyText(text: string, done = 'Copied') {
  return navigator.clipboard
    .writeText(text)
    .then(() => toast.success(done))
    .catch(() => toast.error('Could not copy. Select the text and copy it.'))
}

export function LinkBox({ link, label = 'Invitation link' }: { link: string; label?: string }) {
  return (
    <div className="flex gap-2">
      <Input readOnly value={link} aria-label={label} onFocus={(e) => e.currentTarget.select()} />
      <Button variant="outline" onClick={() => void copyText(link, 'Link copied')}>
        <Copy /> Copy
      </Button>
    </div>
  )
}
