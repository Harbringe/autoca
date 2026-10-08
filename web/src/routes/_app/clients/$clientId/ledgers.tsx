import { createFileRoute } from '@tanstack/react-router'
import { MastersScreen } from '@/features/masters/MastersScreen'

export const Route = createFileRoute('/_app/clients/$clientId/ledgers')({
  validateSearch: (search: Record<string, unknown>): { ledger?: string } => ({
    ledger: typeof search.ledger === 'string' && search.ledger ? search.ledger : undefined,
  }),
  component: LedgersRoute,
})

function LedgersRoute() {
  const { clientId } = Route.useParams()
  const { ledger } = Route.useSearch()
  return <MastersScreen clientId={clientId} tab="ledgers" ledgerId={ledger} />
}
