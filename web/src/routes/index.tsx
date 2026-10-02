import { createFileRoute, redirect } from '@tanstack/react-router'
import { fySearch } from '@/lib/fy'

// The front door is the dashboard, with the financial year the link named (`/?fy=2025`).
export const Route = createFileRoute('/')({
  validateSearch: fySearch,
  beforeLoad: ({ search }) => {
    throw redirect({ to: '/dashboard', search: { fy: search.fy }, replace: true })
  },
})
