import { createFileRoute } from '@tanstack/react-router'
import type { Stage } from '@/api/types'
import { ClientsScreen } from '@/features/clients/ClientsScreen'
import { parseFy } from '@/lib/fy'
import { parseStage } from '@/lib/overview'

// `?stage=` lets a dashboard figure open the list of exactly those clients.
export const Route = createFileRoute('/_app/clients/')({
  validateSearch: (search: Record<string, unknown>): { fy?: number; stage?: Stage } => ({ fy: parseFy(search.fy), stage: parseStage(search.stage) }),
  component: ClientsScreen,
})
