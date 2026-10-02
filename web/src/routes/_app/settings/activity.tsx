import { createFileRoute } from '@tanstack/react-router'
import { ActivityScreen } from '@/features/team/ActivityScreen'

export const Route = createFileRoute('/_app/settings/activity')({ component: ActivityScreen })
