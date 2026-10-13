import { createFileRoute } from '@tanstack/react-router'
import type { ReviewTab } from '@/api/queries/books'
import { ReviewScreen } from '@/features/review/ReviewScreen'

export const Route = createFileRoute('/_app/clients/$clientId/review')({
  validateSearch: (search: Record<string, unknown>): { stage?: ReviewTab; statement?: string } => ({
    stage: (['unresolved', 'pending_approval', 'all', 'posted'] as const).includes(search.stage as ReviewTab) ? (search.stage as ReviewTab) : undefined,
    // One bank statement's id, or "all": the review works through one statement at a time unless told otherwise.
    statement: typeof search.statement === 'string' && search.statement ? search.statement : undefined,
  }),
  component: Screen,
})

function Screen() {
  const { clientId } = Route.useParams()
  const { stage, statement } = Route.useSearch()
  return <ReviewScreen clientId={clientId} stage={stage} statement={statement} />
}
