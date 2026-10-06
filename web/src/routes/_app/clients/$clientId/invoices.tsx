import { createFileRoute } from '@tanstack/react-router'
import { InvoicesScreen } from '@/features/invoices/InvoicesScreen'

export const Route = createFileRoute('/_app/clients/$clientId/invoices')({ component: Screen })

function Screen() {
  const { clientId } = Route.useParams()
  return <InvoicesScreen clientId={clientId} />
}
