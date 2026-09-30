// Under "All clients", a client-scoped module has no books to show yet. Until the module landing
// tables exist this says so plainly and opens the client picker.

import { Users } from 'lucide-react'
import { EmptyState, PageHeader } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { usePageTitle } from '@/lib/title'
import { usePalette } from './CommandPalette'

export function PickClient({ title, description }: { title: string; description: string }) {
  const palette = usePalette()
  usePageTitle(title)
  return (
    <div className="grid gap-4">
      <PageHeader title={title} description={description} />
      <EmptyState
        title="Pick a client"
        action={
          <Button onClick={() => palette.open()}>
            <Users /> Choose a client
          </Button>
        }
      >
        {title} works on one client’s books at a time. Choose a client to open it, or press Alt + C.
      </EmptyState>
    </div>
  )
}
