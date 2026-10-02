import { createFileRoute } from '@tanstack/react-router'
import { GstLanding } from '@/features/gst/GstLanding'
import { parseFy } from '@/lib/fy'

export const Route = createFileRoute('/_app/gst')({
  validateSearch: (search: Record<string, unknown>): { fy?: number } => ({ fy: parseFy(search.fy) }),
  component: GstLanding,
})
