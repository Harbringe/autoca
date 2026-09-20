// Who is signed in, for the whole tree.
//
// The permission list from /me/ decides what the screens *offer*. It decides
// nothing about what the server *allows*: every permission is checked again on
// every request, and a hidden button is not a permission system.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, ApiError, onAuthFailure, V1 } from '../api/client'
import type { Me } from '../api/types'

export type AuthState =
  | { kind: 'loading' }
  | { kind: 'anonymous' }
  | { kind: 'mfa'; step: 'setup' | 'verify' }
  | { kind: 'ready'; me: Me }
  | { kind: 'blocked'; detail: string }

interface SessionValue {
  state: AuthState
  me: Me | null
  can: (permission: string) => boolean
  refresh: () => Promise<void>
  signOut: () => Promise<void>
  setMfa: (step: 'setup' | 'verify') => void
}

const SessionContext = createContext<SessionValue | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ kind: 'loading' })

  const refresh = useCallback(async () => {
    try {
      const me = await api.get<Me>(`${V1}/me/`)
      setState({ kind: 'ready', me })
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.code === 'mfa_enrolment_required') return setState({ kind: 'mfa', step: 'setup' })
        if (error.code === 'mfa_required') return setState({ kind: 'mfa', step: 'verify' })
        if (error.code === 'no_firm' || error.code === 'firm_inactive') {
          return setState({ kind: 'blocked', detail: error.message })
        }
      }
      setState({ kind: 'anonymous' })
    }
  }, [])

  useEffect(() => {
    void refresh()
    return onAuthFailure((error) => {
      if (error.code === 'mfa_enrolment_required') setState({ kind: 'mfa', step: 'setup' })
      else if (error.code === 'mfa_required') setState({ kind: 'mfa', step: 'verify' })
      else setState({ kind: 'anonymous' })
    })
  }, [refresh])

  const signOut = useCallback(async () => {
    try {
      await api.post('/auth/logout/')
    } finally {
      setState({ kind: 'anonymous' })
    }
  }, [])

  const value = useMemo<SessionValue>(() => {
    const me = state.kind === 'ready' ? state.me : null
    return {
      state,
      me,
      can: (permission) => !!me && me.permissions.includes(permission),
      refresh,
      signOut,
      setMfa: (step) => setState({ kind: 'mfa', step }),
    }
  }, [state, refresh, signOut])

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext)
  if (!value) throw new Error('useSession outside SessionProvider')
  return value
}
