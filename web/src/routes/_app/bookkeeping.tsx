import { createFileRoute } from '@tanstack/react-router'
import { PickClient } from '@/features/shell/PickClient'
import { parseFy } from '@/lib/fy'

export const Route = createFileRoute('/_app/bookkeeping')({
  validateSearch: (search: Record<string, unknown>): { fy?: number } => ({ fy: parseFy(search.fy) }),
  component: () => <PickClient title="Bookkeeping" description="Day Book, Ledgers, Parties and rules, and Books and sign-off." />,
})
