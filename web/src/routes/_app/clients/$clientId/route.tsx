import { createFileRoute } from '@tanstack/react-router'
import { parseFy } from '@/lib/fy'
import { Workspace } from '@/features/clients/Workspace'

export const Route = createFileRoute('/_app/clients/$clientId')({
  // `?fy=2025` opens FY 2025-26 on any tab of the client; useFy reads it.
  validateSearch: (search: Record<string, unknown>): { fy?: number } => ({ fy: parseFy(search.fy) }),
  component: ClientWorkspace,
})

function ClientWorkspace() {
  const { clientId } = Route.useParams()
  return <Workspace clientId={clientId} />
}
