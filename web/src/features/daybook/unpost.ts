// Taking entries the assistant posted back out of the books.
//
// Rules the firm trusts post some entries on upload with nobody looking. A CA who disagrees
// unposts them: each entry leaves the books (kept in its change log) and its bank row goes
// back to Review to be decided by a person. Only entries in books not yet signed off can be
// unposted; the server refuses the rest.

import { useQueryClient } from '@tanstack/react-query'
import { raw } from '@/api/client'
import { clientKeys, V1 } from '@/api/queries/clients'
import type { JournalEntry } from '@/api/types'

export const isAssistantEntry = (e: JournalEntry) => !!e.marker && !e.is_locked

export function unpostEntry(entry: JournalEntry, note: string) {
  return raw.post(`${V1}/journal-entries/${entry.id}/remove/`, { note })
}

/** Unpost several, one by one, and report what happened. Stops at nothing: a refusal is counted, not fatal. */
export function useUnpostMany(clientId: string) {
  const queryClient = useQueryClient()
  return async (entries: JournalEntry[], note: string) => {
    let done = 0
    const failed: string[] = []
    for (const entry of entries) {
      try {
        await unpostEntry(entry, note)
        done += 1
      } catch (e) {
        failed.push(`${entry.voucher_type} ${entry.entry_no}: ${e instanceof Error ? e.message : 'refused'}`)
      }
    }
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: clientKeys.one(clientId) }),
      queryClient.invalidateQueries({ queryKey: clientKeys.all }),
    ])
    return { done, failed }
  }
}
