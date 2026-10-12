// How many changes are on their way to the server right now.
//
// Every write goes through apiFetch, so counting there covers all of them, whether a screen uses a mutation, a plain call or a
// loop. The shell shows a small "Saving…" mark from it, so a change that is waiting on the server is never silent, even where a
// screen has no loader of its own. Reads are not counted: they have their own spinners and skeletons.

import { useEffect, useState, useSyncExternalStore } from 'react'

let count = 0
const listeners = new Set<() => void>()

function emit() {
  listeners.forEach((listener) => listener())
}

/** Wraps one write: counts it while it runs, whatever the outcome. */
export async function trackWrite<T>(work: () => Promise<T>): Promise<T> {
  count += 1
  emit()
  try {
    return await work()
  } finally {
    count -= 1
    emit()
  }
}

const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Writes in flight. */
export const usePendingWrites = () => useSyncExternalStore(subscribe, () => count, () => 0)

/**
 * Whether to show the "Saving…" mark. A write that finishes in under a quarter of a second shows nothing, so a quick save does not
 * flash it; once shown it stays for at least half a second, so it does not blink either.
 */
export function useSavingMark(): boolean {
  const pending = usePendingWrites() > 0
  const [shown, setShown] = useState(false)
  useEffect(() => {
    if (pending) {
      const timer = setTimeout(() => setShown(true), 250)
      return () => clearTimeout(timer)
    }
    const timer = setTimeout(() => setShown(false), 500)
    return () => clearTimeout(timer)
  }, [pending])
  return shown
}
