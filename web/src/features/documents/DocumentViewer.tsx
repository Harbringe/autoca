// A stored file shown as pages beside a form: next and previous, zoom, and the original one click away. A PDF, a photo, or
// a spreadsheet or Word file converted to pages by the server, all look the same here. The page images are plain
// same-origin images, so nothing about the page's security policy has to loosen to show them.

import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Download, ZoomIn, ZoomOut } from 'lucide-react'
import { useState } from 'react'
import { raw } from '@/api/client'
import { V1 } from '@/api/queries/clients'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface Preview {
  pages: number
  filename: string
}

const ZOOMS = [0.75, 1, 1.5, 2]

/** What the viewer looks like while a file is still being read: a blank page that breathes. */
export function ViewerSkeleton({ label }: { label?: string }) {
  return (
    <div className="grid h-full min-h-[28rem] place-items-center rounded-md border bg-muted/30 p-6" aria-busy="true">
      <div className="grid w-full max-w-sm gap-3">
        <div className="skeleton h-5 w-2/3 rounded" aria-hidden />
        <div className="skeleton h-3 w-full rounded" aria-hidden />
        <div className="skeleton h-3 w-5/6 rounded" aria-hidden />
        <div className="skeleton mt-3 h-24 w-full rounded" aria-hidden />
        <div className="skeleton h-3 w-4/6 rounded" aria-hidden />
        <div className="skeleton h-3 w-3/6 rounded" aria-hidden />
        <p className="mt-2 text-center text-sm text-muted-foreground">{label ?? 'Reading the file…'}</p>
      </div>
    </div>
  )
}

export function DocumentViewer({ documentId, className }: { documentId: string; className?: string }) {
  const info = useQuery({
    queryKey: ['documents', documentId, 'preview'],
    queryFn: () => raw.get<Preview>(`${V1}/documents/${documentId}/preview/`),
    retry: false,
    staleTime: 300_000,
  })
  const [page, setPage] = useState(1)
  const [zoom, setZoom] = useState(1)
  const [loaded, setLoaded] = useState<number | null>(null)
  const pages = info.data?.pages ?? 0

  if (info.isPending) return <ViewerSkeleton label="Preparing the document…" />
  if (info.isError || pages < 1) {
    return (
      <div className="grid h-full min-h-[16rem] place-items-center rounded-md border bg-muted/30 p-6 text-center text-sm text-muted-foreground">
        <div className="grid gap-2">
          <p>This file cannot be shown here.</p>
          <Button asChild size="sm" variant="outline">
            <a href={`${V1}/documents/${documentId}/download/`}>
              <Download /> Download the original
            </a>
          </Button>
        </div>
      </div>
    )
  }

  const go = (to: number) => {
    setPage(Math.min(Math.max(to, 1), pages))
    setLoaded(null)
  }
  return (
    <div className={cn('grid h-full min-h-0 grid-rows-[auto_1fr] gap-2', className)}>
      <div className="no-print flex flex-wrap items-center justify-between gap-2 text-sm">
        <div className="flex items-center gap-1">
          <Button size="icon" variant="ghost" aria-label="Previous page" disabled={page <= 1} onClick={() => go(page - 1)}>
            <ChevronLeft />
          </Button>
          <span className="num min-w-16 text-center" aria-live="polite">
            {page} / {pages}
          </span>
          <Button size="icon" variant="ghost" aria-label="Next page" disabled={page >= pages} onClick={() => go(page + 1)}>
            <ChevronRight />
          </Button>
        </div>
        <div className="flex items-center gap-1">
          <Button size="icon" variant="ghost" aria-label="Zoom out" disabled={zoom <= ZOOMS[0]!} onClick={() => setZoom(ZOOMS[Math.max(ZOOMS.indexOf(zoom) - 1, 0)]!)}>
            <ZoomOut />
          </Button>
          <span className="num min-w-12 text-center">{Math.round(zoom * 100)}%</span>
          <Button size="icon" variant="ghost" aria-label="Zoom in" disabled={zoom >= ZOOMS[ZOOMS.length - 1]!} onClick={() => setZoom(ZOOMS[Math.min(ZOOMS.indexOf(zoom) + 1, ZOOMS.length - 1)]!)}>
            <ZoomIn />
          </Button>
          <Button asChild size="icon" variant="ghost" aria-label="Download the original">
            <a href={`${V1}/documents/${documentId}/download/`}>
              <Download />
            </a>
          </Button>
        </div>
      </div>
      <div className="relative min-h-0 overflow-auto rounded-md border bg-muted/30">
        {loaded !== page && <div className="skeleton absolute inset-0" aria-hidden />}
        <img
          key={page}
          src={`${V1}/documents/${documentId}/preview/${page}/`}
          alt={`Page ${page} of ${pages} of the uploaded file`}
          style={{ width: `${zoom * 100}%`, maxWidth: 'none' }}
          className="block bg-white"
          onLoad={() => setLoaded(page)}
        />
      </div>
    </div>
  )
}
