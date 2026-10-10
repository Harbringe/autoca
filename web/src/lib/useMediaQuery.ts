import { useSyncExternalStore } from 'react'

const supported = () => typeof window !== 'undefined' && typeof window.matchMedia === 'function'

/** Whether a CSS media query matches now, and follows it as the window changes. False where the browser cannot say. */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (listener) => {
      if (!supported()) return () => {}
      const list = window.matchMedia(query)
      list.addEventListener('change', listener)
      return () => list.removeEventListener('change', listener)
    },
    () => (supported() ? window.matchMedia(query).matches : false),
    () => false,
  )
}
