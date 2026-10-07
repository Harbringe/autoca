// Watches the assistant's queue for the client that is open, and shares what it says. The work itself is done by a
// background worker on the server.
//
// The watcher lives once per open client, in the workspace (useAssistantLoop). The status it produces
// goes into a small store keyed by client, so the strip on Bank statements, the one on Review and the
// indicator in the top bar all read the same answer without each asking the server.

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useSyncExternalStore } from 'react'
import { clientKeys, reviewSummary } from '@/api/queries/clients'
import { useSession } from '@/session/session'
import { assistantLine, assistantShort, IDLE_STATUS, isProcessing, statusFromSummary, type AssistantStatus } from './queue'

/** How often the summary is looked at while rows are waiting. */
const WATCH_MS = 4000

const statuses = new Map<string, AssistantStatus>()
const listeners = new Set<() => void>()

const read = (clientId: string): AssistantStatus => statuses.get(clientId) ?? IDLE_STATUS
function write(clientId: string, next: AssistantStatus) {
  statuses.set(clientId, next)
  listeners.forEach((l) => l())
}
const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => void listeners.delete(listener)
}

/** What the assistant is doing for this client (idle for a client that is not open). */
export function useAssistantStatus(clientId: string | undefined): AssistantStatus {
  return useSyncExternalStore(subscribe, () => (clientId ? read(clientId) : IDLE_STATUS))
}

function subscribeVisibility(listener: () => void) {
  document.addEventListener('visibilitychange', listener)
  return () => document.removeEventListener('visibilitychange', listener)
}
/** False while the tab is hidden. */
export function usePageVisible(): boolean {
  return useSyncExternalStore(subscribeVisibility, () => document.visibilityState !== 'hidden', () => true)
}

/** The current time, ticking each second while `active`, for a countdown. */
export function useNow(active: boolean): number {
  return useSyncExternalStore(
    (listener) => {
      if (!active) return () => {}
      const id = setInterval(listener, 1000)
      return () => clearInterval(id)
    },
    () => (active ? Math.floor(Date.now() / 1000) * 1000 : 0),
  )
}

/** The sentence for a strip, kept current (the countdown ticks). */
export function useAssistantLine(clientId: string | undefined): { line: string | null; status: AssistantStatus } {
  const status = useAssistantStatus(clientId)
  const now = useNow(isProcessing(status) || (status.state === 'paused' && status.resumeAt !== null))
  return { line: assistantLine(status, now || Date.now()), status }
}

/** The short form for the top bar. */
export function useAssistantShort(clientId: string | undefined): string | null {
  const status = useAssistantStatus(clientId)
  const now = useNow(isProcessing(status) || (status.state === 'paused' && status.resumeAt !== null))
  return assistantShort(status, now || Date.now())
}

/**
 * Watches the assistant for this client. Reading the waiting rows is done by a background worker on the server, whether
 * or not anyone has a page open; this only keeps the screens current. While rows are waiting (and the tab is visible) the
 * review summary is looked at every few seconds, and when the count falls the rows the worker has placed are fetched.
 */
export function useAssistantLoop(clientId: string) {
  const { can } = useSession()
  const queryClient = useQueryClient()
  const summary = useQuery({
    ...reviewSummary(clientId),
    enabled: can('transaction.view'),
    refetchInterval: (query) => ((query.state.data?.assistant_waiting ?? 0) > 0 ? WATCH_MS : false),
  })
  const data = summary.data
  const waiting = data?.assistant_waiting
  const lastWaiting = useRef<number | undefined>(undefined)

  useEffect(() => {
    if (!data) return
    write(clientId, statusFromSummary(read(clientId), data, Date.now()))
    const before = lastWaiting.current
    lastWaiting.current = data.assistant_waiting
    if (before !== undefined && data.assistant_waiting < before) {
      // The worker placed some rows: they appear in the review list and the counts as it goes.
      void queryClient.invalidateQueries({ queryKey: clientKeys.part(clientId, 'queue') })
      void queryClient.invalidateQueries({ queryKey: clientKeys.one(clientId) })
    }
  }, [clientId, data, queryClient, waiting])
}
