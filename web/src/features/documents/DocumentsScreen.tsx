import { useQuery } from '@tanstack/react-query'
import { raw } from '@/api/client'
import type { Client, Page } from '@/api/types'
import { useSession } from '@/session/session'
import { useMemo } from 'react'
import { ChevronDown, Download, FileText, Folder, FolderOpen } from 'lucide-react'
import { ErrorState, PageHeader } from '@/components/ca/Page'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Spinner } from '@/components/ui/spinner'
import { formatDate } from '@/lib/format'

const V1 = '/api/v1'

export interface FirmDocument {
  id: string
  client_id: string
  client_name: string
  kind: string
  kind_display: string
  original_filename: string
  byte_size: number
  page_count: number
  status: string
  status_display: string
  failure_reason: string
  uploaded_by_name: string | null
  created_at: string
}

const categories: Record<string, string> = {
  BANK_STATEMENT: 'Bank statements', PURCHASE_INVOICE: 'Purchase invoices',
  SALES_INVOICE: 'Sales invoices', GSTR2B: 'GSTR-2B', REGISTER: 'Registers',
  TALLY_EXPORT: 'Tally exports', OTHER: 'Other files',
}
const bytes = (value: number) => value < 1024 * 1024 ? `${Math.max(1, Math.round(value / 1024))} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`
const date = (value: string) => formatDate(value)

export function DocumentsScreen({ clientId }: { clientId?: string }) {
  const { me } = useSession()
  const clients = useQuery({ queryKey: ['documents', 'clients'], queryFn: () => raw.get<Page<Client>>(`${V1}/clients/`, { page_size: 500 }) })
  const documents = useQuery({ queryKey: ['documents', clientId ?? 'firm'], queryFn: () => raw.get<Page<FirmDocument>>(`${V1}/documents/`, { client: clientId, page_size: 500 }) })
  const grouped = useMemo(() => {
    const groups = new Map<string, FirmDocument[]>()
    for (const file of documents.data?.results ?? []) groups.set(file.client_id, [...(groups.get(file.client_id) ?? []), file])
    return groups
  }, [documents.data])
  if (documents.isPending || (!clientId && clients.isPending)) return <Spinner label="Loading documents…" />
  if (documents.error) return <ErrorState error={documents.error} retry={() => void documents.refetch()} />
  if (!clientId && clients.error) return <ErrorState error={clients.error} retry={() => void clients.refetch()} />
  const visibleClients = clientId ? [{ id: clientId, name: documents.data.results[0]?.client_name ?? 'Client' } as Client] : clients.data?.results ?? []
  const total = documents.data.results.length
  return (
    <div className="grid max-w-6xl gap-5">
      {clientId ? <p className="-mt-2 text-sm text-muted-foreground">Files uploaded for this client, arranged by document type.</p> : <PageHeader title="Documents" description="Browse the firm’s client files in one place, arranged by client and document type." />}
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
        <FolderOpen className="size-4 text-primary" /><span className="font-medium text-foreground">{clientId ? visibleClients[0]?.name : (me?.firm?.name ?? 'Firm')}</span>
        <span>·</span><span>{total} {total === 1 ? 'file' : 'files'} shown</span>
        {documents.data.next && <span>· More files are available; narrow the list to a client to browse them.</span>}
      </div>
      <Card className="overflow-hidden">
        {visibleClients.map((client) => {
          const files = grouped.get(client.id) ?? []
          const byKind = new Map<string, FirmDocument[]>()
          for (const file of files) byKind.set(file.kind, [...(byKind.get(file.kind) ?? []), file])
          return <details key={client.id} open={!!clientId || undefined} className="group border-b last:border-b-0">
            <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3.5 hover:bg-muted/50 [&::-webkit-details-marker]:hidden">
              <ChevronDown className="size-4 text-muted-foreground transition-transform group-open:rotate-0 -rotate-90" />
              <Folder className="size-4 text-primary" /><span className="font-medium text-heading">{client.name}</span>
              <span className="ml-auto text-xs text-muted-foreground">{files.length} {files.length === 1 ? 'file' : 'files'}</span>
            </summary>
            <div className="pb-3 pl-8 pr-4">
              {!files.length ? <p className="py-3 pl-8 text-sm text-muted-foreground">No files uploaded yet.</p> :
                [...byKind].map(([kind, entries]) => <details key={kind} className="group/category">
                  <summary className="flex cursor-pointer list-none items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-muted/50 [&::-webkit-details-marker]:hidden"><ChevronDown className="size-3.5 -rotate-90 text-muted-foreground group-open/category:rotate-0" /><Folder className="size-4 text-muted-foreground" /><span>{categories[kind] ?? kind}</span><span className="ml-auto text-xs text-muted-foreground">{entries.length}</span></summary>
                  <ul className="ml-7 border-l pl-4">
                    {entries.map((file) => <li key={file.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b py-2.5 last:border-0">
                      <FileText className="size-4 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1 truncate text-sm font-medium text-heading" title={file.original_filename}>{file.original_filename || file.kind_display}</span>
                      <span className="text-xs text-muted-foreground">{file.status_display}</span><span className="text-xs text-muted-foreground">{bytes(file.byte_size)}</span><time className="text-xs text-muted-foreground">{date(file.created_at)}</time>
                      <Button asChild size="sm" variant="ghost" aria-label={`Download ${file.original_filename}`}><a href={`${V1}/documents/${file.id}/download/`}><Download /></a></Button>
                    </li>)}
                  </ul>
                </details>)}
            </div>
          </details>
        })}
        {!visibleClients.length && <p className="p-8 text-center text-sm text-muted-foreground">No clients are available in your workspace.</p>}
      </Card>
    </div>
  )
}
