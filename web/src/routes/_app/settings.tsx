import { createFileRoute } from '@tanstack/react-router'
import { SettingsLayout } from '@/features/team/SettingsLayout'

export const Route = createFileRoute('/_app/settings')({ component: SettingsLayout })
