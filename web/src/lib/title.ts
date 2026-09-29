import { useEffect } from 'react'

/** The browser tab and history entry name the screen, so several tabs of the app can be told apart. */
export function usePageTitle(title: string | undefined) {
  useEffect(() => {
    if (!title) return
    const before = document.title
    document.title = `${title} · AutoCA`
    return () => {
      document.title = before
    }
  }, [title])
}
