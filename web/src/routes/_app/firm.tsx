import { createFileRoute, redirect } from '@tanstack/react-router'

// Firm settings moved under Settings; the old address keeps working.
export const Route = createFileRoute('/_app/firm')({
  beforeLoad: () => {
    throw redirect({ to: '/settings/firm', replace: true })
  },
})
