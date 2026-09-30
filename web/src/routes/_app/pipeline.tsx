import { createFileRoute } from '@tanstack/react-router'
import { PipelineScreen } from '@/features/work/PipelineScreen'
import { parseFy } from '@/lib/fy'

export const Route = createFileRoute('/_app/pipeline')({
  validateSearch: (search: Record<string, unknown>): { fy?: number } => ({ fy: parseFy(search.fy) }),
  component: PipelineScreen,
})
