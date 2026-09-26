import { createFileRoute } from '@tanstack/react-router'
import { BooksScreen } from '@/features/books/BooksScreen'

export const Route = createFileRoute('/_app/clients/$clientId/books')({ component: Screen })

function Screen() {
  const { clientId } = Route.useParams()
  return <BooksScreen clientId={clientId} />
}
