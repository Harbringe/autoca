// Whether the client panel (the second column) is shown. A person who wants the width for the page hides it; it stays hidden until they
// bring it back, in this browser. Ctrl+B does it from the keyboard, as in a code editor.

import { useSyncExternalStore } from 'react'

const KEY = 'autoca.sidebar.hidden'
const listeners = new Set<() => void>()

function read(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return false
  }
}

let hidden = read()

export function setSidebarHidden(next: boolean) {
  hidden = next
  try {
    localStorage.setItem(KEY, next ? '1' : '0')
  } catch {
    // A browser that will not remember still hides it for this visit.
  }
  listeners.forEach((l) => l())
}

export const toggleSidebar = () => setSidebarHidden(!hidden)

/** True while the client panel is hidden. */
export function useSidebarHidden(): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener)
      return () => void listeners.delete(listener)
    },
    () => hidden,
    () => false,
  )
}
