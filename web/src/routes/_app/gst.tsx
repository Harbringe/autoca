import { createFileRoute, redirect } from '@tanstack/react-router'

// GST reconciliation gets its screens in a later wave; until then it is a "coming soon" page.
export const Route = createFileRoute('/_app/gst')({
  beforeLoad: () => {
    throw redirect({ to: '/soon/$module', params: { module: 'gst' }, replace: true })
  },
})
