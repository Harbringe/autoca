import { createFileRoute } from '@tanstack/react-router'
import { PickClient } from '@/features/shell/PickClient'
import { parseFy } from '@/lib/fy'

export const Route = createFileRoute('/_app/bank')({
  validateSearch: (search: Record<string, unknown>): { fy?: number } => ({ fy: parseFy(search.fy) }),
  component: () => <PickClient title="Bank statements" description="Upload statements, place each row in a ledger, and post to the Day Book." />,
})
