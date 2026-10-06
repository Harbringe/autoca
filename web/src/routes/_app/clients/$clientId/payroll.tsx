import { createFileRoute } from '@tanstack/react-router'
import { PayrollScreen } from '@/features/payroll/PayrollScreen'

export const Route = createFileRoute('/_app/clients/$clientId/payroll')({ component: Screen })

function Screen() {
  const { clientId } = Route.useParams()
  return <PayrollScreen clientId={clientId} />
}
