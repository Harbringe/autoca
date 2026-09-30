import { createFileRoute } from '@tanstack/react-router'
import { FirmScreen } from '@/features/team/FirmScreen'

export const Route = createFileRoute('/_app/settings/firm')({ component: FirmScreen })
