import { createFileRoute } from '@tanstack/react-router'
import type { ReviewTab } from '@/api/queries/books'
import { ReviewScreen } from '@/features/review/ReviewScreen'

export const Route = createFileRoute('/_app/clients/$clientId/review')({
  validateSearch: (search: Record<string, unknown>): { stage?: ReviewTab } => ({
    stage: (['unresolved', 'pending_approval', 'all', 'posted'] as const).includes(search.stage as ReviewTab) ? (search.stage as ReviewTab) : undefined,
  }),
  component: Screen,
})

function Screen() {
  const { clientId } = Route.useParams()
  const { stage } = Route.useSearch()
  return <ReviewScreen clientId={clientId} stage={stage} />
}
