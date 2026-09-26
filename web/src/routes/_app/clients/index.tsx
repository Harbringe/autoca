import { createFileRoute } from '@tanstack/react-router'
import { ClientsScreen } from '@/features/clients/ClientsScreen'

export const Route = createFileRoute('/_app/clients/')({ component: ClientsScreen })
