import { createFileRoute } from '@tanstack/react-router'
import { ClientGst } from '@/features/gst/ClientGst'

export const Route = createFileRoute('/_app/clients/$clientId/gst')({
  // `?run=` is the run being looked at; anything that is not an id is dropped.
  validateSearch: (search: Record<string, unknown>): { run?: string } => ({
    run: typeof search.run === 'string' && /^[0-9a-f-]{32,36}$/i.test(search.run) ? search.run : undefined,
  }),
  component: Screen,
})

function Screen() {
  const { clientId } = Route.useParams()
  const { run } = Route.useSearch()
  return <ClientGst clientId={clientId} runId={run} />
}
