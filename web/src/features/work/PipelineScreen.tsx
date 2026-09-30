// Work pipeline: where each client's books stand. The board and allocation views arrive in a later
// wave; until then this shows the firm's open work by client, which is the same data.

import { Link } from '@tanstack/react-router'
import { EmptyState, PageHeader } from '@/components/ca/Page'
import { usePageTitle } from '@/lib/title'
import { useSession } from '@/session/session'
import { WaitingOnClients } from './WorkScreen'

export function PipelineScreen() {
  const { can } = useSession()
  usePageTitle('Work pipeline')
  return (
    <div className="grid gap-5">
      <PageHeader title="Work pipeline" description="Where each client’s books stand, and who is on them." />
      {can('team.view') ? (
        <WaitingOnClients />
      ) : (
        <EmptyState title="Your work is under Staff performance">
          <Link to="/staff" className="text-link underline">
            Open what is waiting on you
          </Link>
        </EmptyState>
      )}
    </div>
  )
}
