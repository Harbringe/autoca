import { useEffect, useRef } from 'react'
import { useRouterState } from '@tanstack/react-router'

/**
 * How the person last gave input. A new page moves focus to its heading so a keyboard or screen-reader
 * user starts at the top; for someone who clicked, that heading must not grow a focus ring. Browsers
 * decide this inconsistently when the clicked link has just left the page, so it is decided here.
 */
export type InputModality = 'pointer' | 'keyboard'
// Until a key is pressed nobody is navigating by keyboard, so a heading focused on its own shows no ring.
let modality: InputModality = 'pointer'
export const setInputModality = (next: InputModality) => {
  modality = next
}
export const inputModality = () => modality

/** Starts listening for the last kind of input; returns the stop function. */
export function trackInputModality(target: Document = document): () => void {
  const pointer = () => setInputModality('pointer')
  const key = (e: KeyboardEvent) => {
    // A bare modifier is not navigation.
    if (!['Shift', 'Control', 'Alt', 'Meta'].includes(e.key)) setInputModality('keyboard')
  }
  target.addEventListener('pointerdown', pointer, true)
  target.addEventListener('keydown', key, true)
  return () => {
    target.removeEventListener('pointerdown', pointer, true)
    target.removeEventListener('keydown', key, true)
  }
}

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
  if (modality === 'pointer') {
    // Focus is for assistive technology here; there is nothing for the eye to see.
    target.setAttribute('data-pointer-focus', '')
    target.addEventListener('blur', () => target.removeAttribute('data-pointer-focus'), { once: true })
  } else {
    target.removeAttribute('data-pointer-focus')
  }
  target.focus({ preventScroll: false })
  return true
}

export function useRouteFocus() {
  const path = useRouterState({ select: (s) => s.location.pathname })
  const shown = useRef(path)
  useEffect(() => trackInputModality(), [])
  useEffect(() => {
    // The first paint is the browser's own page load; focus is only moved by navigating inside the app.
    if (shown.current === path) return
    shown.current = path
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
