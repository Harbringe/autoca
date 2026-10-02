import { createFileRoute } from '@tanstack/react-router'
import { DashboardScreen } from '@/features/dashboard/DashboardScreen'
import { fySearch } from '@/lib/fy'

export const Route = createFileRoute('/_app/dashboard')({ validateSearch: fySearch, component: DashboardScreen })
