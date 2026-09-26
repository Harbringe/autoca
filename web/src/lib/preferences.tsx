// Per-person conveniences: theme, row density, and the financial year in view.
//
// These live in the browser only. They are how *this* person likes the screen,
// not facts about any client, so they survive a reload and are never sent
// anywhere. Storage can be unavailable (a private window, blocked site data),
// and the app has to look right without it.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { financialYearOf } from './format'

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

interface Preferences {
  theme: Theme
  setTheme: (theme: Theme) => void
  density: Density
  setDensity: (density: Density) => void
  /** The financial year on screen, by the year it starts in (2025 is FY 2025-26). */
  fy: number
  setFy: (fy: number) => void
}

const Ctx = createContext<Preferences | null>(null)

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => (read('autoca.theme') as Theme) || 'system')
  const [density, setDensityState] = useState<Density>(() => (read('autoca.density') as Density) || 'comfortable')
  const [fy, setFyState] = useState<number>(() => Number(read('autoca.fy')) || financialYearOf(new Date()))

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
  const setFy = useCallback((next: number) => {
    setFyState(next)
    write('autoca.fy', String(next))
  }, [])

  const value = useMemo(
    () => ({ theme, setTheme, density, setDensity, fy, setFy }),
    [theme, setTheme, density, setDensity, fy, setFy],
  )
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function usePreferences(): Preferences {
  const value = useContext(Ctx)
  if (!value) throw new Error('usePreferences outside PreferencesProvider')
  return value
}
