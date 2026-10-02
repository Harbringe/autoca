import { createFileRoute } from '@tanstack/react-router'
import { PreferencesScreen } from '@/features/team/PreferencesScreen'

export const Route = createFileRoute('/_app/settings/preferences')({ component: PreferencesScreen })
