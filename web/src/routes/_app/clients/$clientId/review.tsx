import { createFileRoute } from '@tanstack/react-router'
import type { Stage } from '@/api/queries/books'
import { ReviewScreen } from '@/features/review/ReviewScreen'

export const Route = createFileRoute('/_app/clients/$clientId/review')({
  validateSearch: (search: Record<string, unknown>): { stage?: Stage } => ({
    stage: (['unresolved', 'pending_approval', 'all'] as const).includes(search.stage as Stage) ? (search.stage as Stage) : undefined,
  }),
  component: Screen,
})

function Screen() {
  const { clientId } = Route.useParams()
  const { stage } = Route.useSearch()
  return <ReviewScreen clientId={clientId} stage={stage} />
}
