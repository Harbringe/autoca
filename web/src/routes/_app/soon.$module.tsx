import { createFileRoute, redirect } from '@tanstack/react-router'
import { SoonScreen } from '@/features/soon/SoonScreen'

export const Route = createFileRoute('/_app/soon/$module')({
  // GST had a "coming soon" page until it was built; an old bookmark goes to the real screen.
  beforeLoad: ({ params }) => {
    if (params.module === 'gst') throw redirect({ to: '/gst', replace: true })
  },
  component: Screen,
})

function Screen() {
  return <SoonScreen module={Route.useParams().module} />
}
