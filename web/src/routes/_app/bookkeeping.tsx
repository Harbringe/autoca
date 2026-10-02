import { createFileRoute } from '@tanstack/react-router'
import { ModuleClientTable } from '@/features/shell/ModuleClientTable'
import { parseFy } from '@/lib/fy'

export const Route = createFileRoute('/_app/bookkeeping')({
  validateSearch: (search: Record<string, unknown>): { fy?: number } => ({ fy: parseFy(search.fy) }),
  component: () => <ModuleClientTable module="bookkeeping" />,
})
