// The client the person is working on, remembered for this browser tab so the sidebar can keep
// pointing at it when they step out to the dashboard or the client list. It is only an id: the
// name and everything else is read from the server, and it is gone when the tab closes.

import { useSyncExternalStore } from 'react'

const KEY = 'autoca.selectedClient'
const listeners = new Set<() => void>()

function read(): string | null {
  try {
    return sessionStorage.getItem(KEY)
  } catch {
    return null
  }
}

let memory: string | null = read()

export function setSelectedClient(id: string | null) {
  if (id === memory) return
  memory = id
  try {
    if (id) sessionStorage.setItem(KEY, id)
    else sessionStorage.removeItem(KEY)
  } catch {
    // Without storage the choice lasts until the page reloads.
  }
  listeners.forEach((listener) => listener())
}

export function useSelectedClient(): string | null {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => memory,
    () => null,
  )
}
