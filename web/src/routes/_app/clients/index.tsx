import { createFileRoute } from '@tanstack/react-router'
import { ClientsScreen } from '@/features/clients/ClientsScreen'
import { fySearch } from '@/lib/fy'

export const Route = createFileRoute('/_app/clients/')({ validateSearch: fySearch, component: ClientsScreen })
