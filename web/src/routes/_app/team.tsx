import { createFileRoute, redirect } from '@tanstack/react-router'

// Team & roles moved under Settings; the old address keeps working.
export const Route = createFileRoute('/_app/team')({
  beforeLoad: () => {
    throw redirect({ to: '/settings/team', replace: true })
  },
})
