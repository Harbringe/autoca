import { useEffect, useRef } from 'react'
import { useRouterState } from '@tanstack/react-router'

/**
 * A new page is announced by moving focus to its h1 (or, failing that, the main region), so a
 * keyboard or screen-reader user starts reading at the top instead of on a link that is gone.
 * Focus stays put when it is already inside the page (a tab, a filter), and a page that is still
 * loading gets a moment to draw its heading.
 */
export function focusPageHeading(main: HTMLElement | null, { force = false }: { force?: boolean } = {}): boolean {
  if (!main) return false
  const active = document.activeElement
  const insideMain = active instanceof HTMLElement && active !== main && main.contains(active) && active.isConnected
  if (insideMain && !force) return true
  const heading = main.querySelector<HTMLElement>('h1')
  const target = heading ?? (force ? main : null)
  if (!target) return false
  if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1')
  target.focus({ preventScroll: false })
  return true
}

export function useRouteFocus() {
  const path = useRouterState({ select: (s) => s.location.pathname })
  const first = useRef(true)
  useEffect(() => {
    // The first paint is the browser's own page load; focus is only moved by navigating inside the app.
    if (first.current) {
      first.current = false
      return
    }
    const main = document.getElementById('content')
    let tries = 0
    const timer = window.setInterval(() => {
      tries += 1
      // After ~1.5 s with no heading (a slow or failed load) the region itself takes focus.
      if (focusPageHeading(main) || (tries >= 10 && focusPageHeading(main, { force: true }))) window.clearInterval(timer)
    }, 150)
    return () => window.clearInterval(timer)
  }, [path])
}
