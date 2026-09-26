import { createFileRoute } from '@tanstack/react-router'
import { InviteScreen } from '@/features/auth/InviteScreen'

export const Route = createFileRoute('/invite/$token')({ component: Invite })

function Invite() {
  const { token } = Route.useParams()
  return <InviteScreen token={token} />
}
