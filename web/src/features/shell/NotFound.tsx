// A path that is not a screen. It renders inside the shell (the sidebar and top bar stay), says so
// plainly, and offers the two ways back.

import { Link } from '@tanstack/react-router'
import { PageHeader } from '@/components/ca/Page'
import { usePageTitle } from '@/lib/title'

export function NotFound() {
  usePageTitle('Page not found')
  return (
    <div className="grid max-w-prose gap-4">
      <PageHeader title="This page does not exist" description="The address may be out of date, or mistyped." className="mb-0" />
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
        <Link to="/dashboard" className="font-medium text-link underline underline-offset-2">
          Go to the dashboard
        </Link>
        <Link to="/clients" className="font-medium text-link underline underline-offset-2">
          Go to Clients
        </Link>
      </p>
    </div>
  )
}
