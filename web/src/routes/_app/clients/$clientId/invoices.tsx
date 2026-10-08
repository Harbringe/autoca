import { createFileRoute, redirect } from '@tanstack/react-router'

// Invoices and bills are one list now: Purchases & Sales.
export const Route = createFileRoute('/_app/clients/$clientId/invoices')({
  beforeLoad: ({ params }) => {
    throw redirect({ to: '/clients/$clientId/bills', params: { clientId: params.clientId } })
  },
})
