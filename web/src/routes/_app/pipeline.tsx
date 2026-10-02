import { createFileRoute } from '@tanstack/react-router'
import { parsePipelineView, PipelineScreen, type PipelineView } from '@/features/work/PipelineScreen'
import { parseFy } from '@/lib/fy'

export const Route = createFileRoute('/_app/pipeline')({
  validateSearch: (search: Record<string, unknown>): { fy?: number; view?: PipelineView } => ({
    fy: parseFy(search.fy),
    view: parsePipelineView(search.view),
  }),
  component: Screen,
})

function Screen() {
  return <PipelineScreen view={Route.useSearch().view ?? 'board'} />
}
