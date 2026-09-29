import { createFileRoute } from '@tanstack/react-router'
import { TeamScreen } from '@/features/team/TeamScreen'

export const Route = createFileRoute('/_app/team')({ component: TeamScreen })
