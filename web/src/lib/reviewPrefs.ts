// "Search every bank statement": whether the search box in Review looks through all of a client's statements or only the one being
// reviewed. Kept in this browser, like the other conveniences, and read through a small store so the Review screen and the
// Preferences screen always agree.

import { useSyncExternalStore } from 'react'

const KEY = 'autoca.review.searchAllStatements'
const listeners = new Set<() => void>()

function read(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

let on = read()

export function setSearchAllStatements(next: boolean) {
  on = next
  try {
    localStorage.setItem(KEY, next ? '1' : '0')
  } catch {
    // It still applies for this visit.
  }
  listeners.forEach((l) => l())
}

/** True when a search in Review covers every statement. */
export function useSearchAllStatements(): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => void listeners.delete(listener)
    },
    () => on,
    () => false,
  )
}
