// Alt+C opens the client switcher when one is on screen (inside a client), and the command palette
// otherwise. The switcher says it is there by registering here; the palette's key asks.

const openers = new Set<() => void>()

export function registerSwitcher(open: () => void): () => void {
  openers.add(open)
  return () => void openers.delete(open)
}

/** Opens the switcher on screen, if any. False means there is none and the caller should do something else. */
export function openClientSwitcher(): boolean {
  const last = [...openers].pop()
  if (!last) return false
  last()
  return true
}
