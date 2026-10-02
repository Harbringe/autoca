import { createFileRoute } from '@tanstack/react-router'
import { NotFound } from '@/features/shell/NotFound'

// Any address that is not a screen: drawn inside the shell, so the way back is one click.
export const Route = createFileRoute('/_app/$')({ component: NotFound })
