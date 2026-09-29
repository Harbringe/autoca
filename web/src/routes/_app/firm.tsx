import { createFileRoute } from '@tanstack/react-router'
import { FirmScreen } from '@/features/team/FirmScreen'

export const Route = createFileRoute('/_app/firm')({ component: FirmScreen })
