import { createFileRoute, redirect } from '@tanstack/react-router'

// Until the dashboard is built (it needs the firm overview endpoint) this lands on the client list.
export const Route = createFileRoute('/_app/dashboard')({
  beforeLoad: () => {
    throw redirect({ to: '/clients', replace: true })
  },
})
