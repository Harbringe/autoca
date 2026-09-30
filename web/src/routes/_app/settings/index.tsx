import { createFileRoute } from '@tanstack/react-router'
import { SettingsHome } from '@/features/team/SettingsLayout'

export const Route = createFileRoute('/_app/settings/')({ component: SettingsHome })
