import { createFileRoute, redirect } from '@tanstack/react-router'
import { parseWorkSearch } from '@/features/work/WorkScreen'

// /work became /staff (Staff performance). The old address keeps working, with its period and person.
export const Route = createFileRoute('/_app/work')({
  validateSearch: parseWorkSearch,
  beforeLoad: ({ search }) => {
    throw redirect({ to: '/staff', search, replace: true })
  },
})
