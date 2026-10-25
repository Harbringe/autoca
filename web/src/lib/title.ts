import { useQuery } from '@tanstack/react-query'
import { useParams } from '@tanstack/react-router'
import { useEffect } from 'react'
import { clientDetail } from '@/api/queries/clients'

/**
 * The browser tab and history entry name the screen, so several tabs of the app can be told apart.
 * Inside a client the client's name follows ("Day Book · QA Sharma Traders · AutoCA"); the client is
 * read from the address and the lookup is the one the header already made, so it costs no request.
 */
export function usePageTitle(title: string | undefined) {
  const { clientId } = useParams({ strict: false }) as { clientId?: string }
  const client = useQuery({ ...clientDetail(clientId ?? ''), enabled: !!clientId })
  const name = clientId ? client.data?.name : undefined
  useEffect(() => {
    if (!title) return
    const before = document.title
    document.title = [title, name, 'AutoCA'].filter(Boolean).join(' · ')
    return () => {
      document.title = before
    }
  }, [title, name])
}
