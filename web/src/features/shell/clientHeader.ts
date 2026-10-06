import { useQueries, useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { booksStatus, clientDetail } from '@/api/queries/clients'
import { BOOKS_STATE_LABEL, booksState } from '@/features/books/state'
import { fyLabel } from '@/lib/format'
import { recordRecentClient } from '@/lib/recentClients'
import { useSession } from '@/session/session'
import { useFy } from './useFy'

/**
 * What the panel and the phone's client button say about the client in the address: the full name and
 * "FY 2026-27 · Working draft". Opening a client that loads is also what puts it among the recent ones.
 */
export function useClientHeader(clientId: string) {
  const { can } = useSession()
  const client = useQuery(clientDetail(clientId))
  const books = useQuery({ ...booksStatus(clientId), enabled: can('report.view') })
  const { fy } = useFy()
  const name = client.data?.name
  useEffect(() => {
    if (name) recordRecentClient(clientId)
  }, [clientId, name])
  const fyText = `FY ${fyLabel(fy)}`
  const stateLabel = books.data ? BOOKS_STATE_LABEL[booksState(books.data)] : undefined
  return { name, fyText, stateLabel, line: [fyText, stateLabel].filter(Boolean).join(' · ') }
}

/** Names for remembered client ids. An id that does not load (gone, or not this person's) is left out. */
export function useClientNames(ids: string[]): { id: string; name: string }[] {
  const results = useQueries({ queries: ids.map((id) => ({ ...clientDetail(id), retry: false })) })
  return ids.flatMap((id, i) => {
    const name = results[i]?.data?.name
    return name ? [{ id, name }] : []
  })
}
