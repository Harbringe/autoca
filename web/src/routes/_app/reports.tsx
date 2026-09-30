import { createFileRoute } from '@tanstack/react-router'
import { PickClient } from '@/features/shell/PickClient'
import { parseFy } from '@/lib/fy'

export const Route = createFileRoute('/_app/reports')({
  validateSearch: (search: Record<string, unknown>): { fy?: number } => ({ fy: parseFy(search.fy) }),
  component: () => <PickClient title="Reports" description="Trial Balance, Profit and Loss, Balance Sheet and bank reconciliation." />,
})
