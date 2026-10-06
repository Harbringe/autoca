// The clients this person opened lately, and the ones they pinned, kept in this browser only. They
// are ids and nothing else: names and everything about a client are read from the server, and an id
// the server no longer knows (or that this person cannot see) is simply not shown.

import { useSyncExternalStore } from 'react'

const RECENT_KEY = 'autoca.recentClients'
const PINNED_KEY = 'autoca.pinnedClients'
export const MAX_RECENT = 5
export const MAX_PINNED = 12

export interface ClientMemory {
  recent: string[]
  pinned: string[]
}

/** Whatever is in storage, if it is a list of text; anything else is nothing. */
export function parseIds(raw: string | null): string[] {
  if (!raw) return []
  try {
    const value: unknown = JSON.parse(raw)
    return Array.isArray(value) ? [...new Set(value.filter((v): v is string => typeof v === 'string' && v.length > 0))] : []
  } catch {
    return []
  }
}

/** The id moves to the front; the list never grows past `max`. */
export function pushRecent(list: string[], id: string, max = MAX_RECENT): string[] {
  return [id, ...list.filter((x) => x !== id)].slice(0, max)
}

/** Pinned if it was not, unpinned if it was. New pins go to the end, so the order stays as the person made it. */
export function togglePin(list: string[], id: string, max = MAX_PINNED): string[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id].slice(-max)
}

function read(key: string): string[] {
  try {
    return parseIds(localStorage.getItem(key))
  } catch {
    return []
  }
}

function write(key: string, ids: string[]) {
  try {
    localStorage.setItem(key, JSON.stringify(ids))
  } catch {
    // Without storage the list lasts until the page reloads.
  }
}

let memory: ClientMemory = { recent: read(RECENT_KEY), pinned: read(PINNED_KEY) }
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())

const same = (a: string[], b: string[]) => a.length === b.length && a.every((x, i) => x === b[i])

export function recordRecentClient(id: string) {
  const recent = pushRecent(memory.recent, id)
  if (same(recent, memory.recent)) return
  memory = { ...memory, recent }
  write(RECENT_KEY, recent)
  emit()
}

export function toggleClientPin(id: string) {
  const pinned = togglePin(memory.pinned, id)
  memory = { ...memory, pinned }
  write(PINNED_KEY, pinned)
  emit()
}

/** For tests: forget everything, in memory and in storage. */
export function resetClientMemory() {
  memory = { recent: [], pinned: [] }
  try {
    localStorage.removeItem(RECENT_KEY)
    localStorage.removeItem(PINNED_KEY)
  } catch {
    // nothing to clear
  }
  emit()
}

// Another tab changed the lists: read them again. The snapshot is replaced, never mutated.
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key !== RECENT_KEY && e.key !== PINNED_KEY) return
    memory = { recent: read(RECENT_KEY), pinned: read(PINNED_KEY) }
    emit()
  })
}

export function useClientMemory(): ClientMemory {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    () => memory,
    () => memory,
  )
}
