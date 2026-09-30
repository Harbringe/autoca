// Per-person conveniences: theme, row density, and the financial year in view.
//
// These live in the browser only. They are how *this* person likes the screen,
// not facts about any client, so they survive a reload and are never sent
// anywhere. Storage can be unavailable (a private window, blocked site data),
// and the app has to look right without it.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type Theme = 'light' | 'dark' | 'system'
export type Density = 'comfortable' | 'compact'

function read(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* the preference just won't outlive this tab */
  }
}

function prefersDark(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches
}

function readFyMap(): Record<string, number> {
  try {
    const parsed: unknown = JSON.parse(read('autoca.fyByClient') ?? '{}')
    if (!parsed || typeof parsed !== 'object') return {}
    return Object.fromEntries(Object.entries(parsed).filter(([, v]) => Number.isInteger(v)))
  } catch {
    return {}
  }
}

interface Preferences {
  theme: Theme
  setTheme: (theme: Theme) => void
  density: Density
  setDensity: (density: Density) => void
  /** Hide the sidebar items for modules that are not built yet. Off by default, so the whole map shows. */
  hideSoon: boolean
  setHideSoon: (hide: boolean) => void
  /** The financial year each client was last deliberately set to, by the year it starts in (2025 is FY 2025-26). */
  fyByClient: Record<string, number>
  setClientFy: (clientId: string, fy: number) => void
}

const Ctx = createContext<Preferences | null>(null)

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => (read('autoca.theme') as Theme) || 'system')
  const [density, setDensityState] = useState<Density>(() => (read('autoca.density') as Density) || 'comfortable')
  const [hideSoon, setHideSoonState] = useState<boolean>(() => read('autoca.hideSoon') === '1')
  const [fyByClient, setFyByClient] = useState<Record<string, number>>(readFyMap)

  useEffect(() => {
    const dark = theme === 'dark' || (theme === 'system' && prefersDark())
    document.documentElement.classList.toggle('dark', dark)
  }, [theme])

  useEffect(() => {
    document.documentElement.dataset.density = density
  }, [density])

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next)
    write('autoca.theme', next)
  }, [])
  const setDensity = useCallback((next: Density) => {
    setDensityState(next)
    write('autoca.density', next)
  }, [])
  const setHideSoon = useCallback((next: boolean) => {
    setHideSoonState(next)
    write('autoca.hideSoon', next ? '1' : '0')
  }, [])
  const setClientFy = useCallback((clientId: string, next: number) => {
    setFyByClient((prev) => {
      if (prev[clientId] === next) return prev
      const map = { ...prev, [clientId]: next }
      write('autoca.fyByClient', JSON.stringify(map))
      return map
    })
  }, [])

  const value = useMemo(
    () => ({ theme, setTheme, density, setDensity, hideSoon, setHideSoon, fyByClient, setClientFy }),
    [theme, setTheme, density, setDensity, hideSoon, setHideSoon, fyByClient, setClientFy],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function usePreferences(): Preferences {
  const value = useContext(Ctx)
  if (!value) throw new Error('usePreferences outside PreferencesProvider')
  return value
}
