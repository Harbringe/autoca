import { createFileRoute } from '@tanstack/react-router'
import { DocumentsScreen } from '@/features/documents/DocumentsScreen'

export const Route = createFileRoute('/_app/documents')({ component: () => <DocumentsScreen /> })
