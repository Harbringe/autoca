// Runs the assistant's queue for the client that is open, and shares what it says.
//
// The loop lives once per open client, in the workspace (useAssistantLoop). The status it produces
// goes into a small store keyed by client, so the strip on Bank statements, the one on Review and the
// indicator in the top bar all read the same answer without each asking the server.

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useSyncExternalStore } from 'react'
import { raw } from '@/api/client'
import { isApiError } from '@/api/errors'
import { clientKeys, reviewSummary, V1 } from '@/api/queries/clients'
import type { NextBatch } from '@/api/types'
import { useSession } from '@/session/session'
import { assistantLine, assistantShort, IDLE_STATUS, seeded, startAssistantLoop, statusAfter, type AssistantStatus } from './queue'

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
  const now = useNow(status.state === 'paused' && status.resumeAt !== null)
  return { line: assistantLine(status, now || Date.now()), status }
}

/** The short form for the top bar. */
export function useAssistantShort(clientId: string | undefined): string | null {
  const status = useAssistantStatus(clientId)
  const now = useNow(status.state === 'paused' && status.resumeAt !== null)
  return assistantShort(status, now || Date.now())
}

/**
 * While this client is open and rows are waiting for the assistant, ask it for the next batch, and
 * again after the pause the server names. Stops when the tab is hidden, when the client is left, and
 * when the server says it is idle. Only people who may classify rows drive it.
 */
export function useAssistantLoop(clientId: string) {
  const { can } = useSession()
  const queryClient = useQueryClient()
  const summary = useQuery({ ...reviewSummary(clientId), enabled: can('transaction.view') })
  const waiting = summary.data?.assistant_waiting
  const visible = usePageVisible()
  const wants = can('transaction.classify') && (waiting ?? 0) > 0

  // What the summary says is waiting, until the assistant has answered.
  useEffect(() => {
    if (waiting !== undefined) write(clientId, seeded(read(clientId), waiting))
  }, [clientId, waiting])

  useEffect(() => {
    if (!wants || !visible) return
    // A server with no model configured said so once; asking again cannot change that.
    if (read(clientId).reason === 'assistant_off') return
    write(clientId, { ...read(clientId), running: true })
    const stop = startAssistantLoop({
      post: () => raw.post<NextBatch>(`${V1}/clients/${clientId}/assistant/next-batch/`),
      onOutcome: (outcome) => {
        write(clientId, statusAfter(read(clientId), outcome, Date.now()))
        if (outcome.processed > 0) {
          // What the batch placed appears in the review list and the counts as it goes.
          void queryClient.invalidateQueries({ queryKey: clientKeys.part(clientId, 'queue') })
          void queryClient.invalidateQueries({ queryKey: clientKeys.part(clientId, 'summary') })
          if (outcome.auto_posted > 0 || outcome.proposed > 0) void queryClient.invalidateQueries({ queryKey: clientKeys.one(clientId) })
        }
      },
      onError: (error) => {
        // Not allowed, or no such client: nothing to retry. Anything else (network, a server error) is tried again.
        const final = isApiError(error) && (error.status === 401 || error.status === 403 || error.status === 404)
        if (!final) write(clientId, { ...read(clientId), state: 'paused', reason: 'provider_down', resumeAt: Date.now() + 30_000 })
        return !final
      },
      onDone: () => {
        write(clientId, { ...read(clientId), running: false })
        void queryClient.invalidateQueries({ queryKey: clientKeys.part(clientId, 'summary') })
      },
    })
    return () => {
      stop()
      write(clientId, { ...read(clientId), running: false })
    }
  }, [clientId, wants, visible, queryClient])
}
