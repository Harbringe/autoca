// Who is signed in, for the whole tree.
//
// Signing in is a sequence, not an event: password, then a second factor (set
// up once, asked for after), then the session is whole. The server enforces
// every step -- a half-signed-in session is refused on every API call with a
// code that says which step is missing -- so this state machine only has to
// follow along and show the right screen.
//
// The permission list from /me/ decides what screens *offer*. It decides
// nothing about what the server allows: every permission is checked again on
// every request, and a hidden button is not a permission system.

import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, type ReactNode } from 'react'
import { api, data, onSessionChange, raw, resetCsrf } from '@/api/client'
import { isApiError } from '@/api/errors'
import type { LoginResponse, Me, MfaStep } from '@/api/types'

export type SessionState =
  | { kind: 'loading' }
  | { kind: 'anonymous' }
  | { kind: 'mfa'; step: MfaStep }
  | { kind: 'blocked'; detail: string }
  /** Signed in, but attached to no firm: the platform owner, whose panel is the admin. */
  | { kind: 'platform'; me: Me }
  | { kind: 'ready'; me: Me }

export type SessionAction =
  | { type: 'anonymous' }
  | { type: 'mfa'; step: MfaStep }
  | { type: 'blocked'; detail: string }
  | { type: 'me'; me: Me }

export function sessionReducer(_: SessionState, action: SessionAction): SessionState {
  switch (action.type) {
    case 'anonymous':
      return { kind: 'anonymous' }
    case 'mfa':
      return { kind: 'mfa', step: action.step }
    case 'blocked':
      return { kind: 'blocked', detail: action.detail }
    case 'me':
      return action.me.firm ? { kind: 'ready', me: action.me } : { kind: 'platform', me: action.me }
  }
}

/** What a failed /me/ call means for the session. Pure, so the rules are testable. */
export function actionForError(error: unknown): SessionAction {
  if (isApiError(error)) {
    if (error.code === 'mfa_enrolment_required') return { type: 'mfa', step: 'setup' }
    if (error.code === 'mfa_required') return { type: 'mfa', step: 'verify' }
    if (error.code === 'no_firm' || error.code === 'firm_inactive') return { type: 'blocked', detail: error.message }
  }
  return { type: 'anonymous' }
}

interface SessionValue {
  state: SessionState
  me: Me | null
  can: (permission: string) => boolean
  /** Re-read who is signed in, and where in the sign-in sequence they are. */
  refresh: () => Promise<void>
  signIn: (email: string, password: string) => Promise<LoginResponse>
  signOut: () => Promise<void>
}

const SessionContext = createContext<SessionValue | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(sessionReducer, { kind: 'loading' })
  const queryClient = useQueryClient()

  const refresh = useCallback(async () => {
    try {
      dispatch({ type: 'me', me: data(await api.GET('/api/v1/me/')) })
    } catch (error) {
      dispatch(actionForError(error))
    }
  }, [])

  useEffect(() => {
    void refresh()
    return onSessionChange((error) => dispatch(actionForError(error)))
  }, [refresh])

  const signIn = useCallback(
    async (email: string, password: string) => {
      const result = await raw.post<LoginResponse>('/auth/login/', { email, password })
      resetCsrf() // signing in rotates the token
      await refresh()
      return result
    },
    [refresh],
  )

  const signOut = useCallback(async () => {
    try {
      await raw.post('/auth/logout/')
    } finally {
      resetCsrf()
      // What was cached belongs to the person who just left.
      queryClient.clear()
      dispatch({ type: 'anonymous' })
    }
  }, [queryClient])

  const value = useMemo<SessionValue>(() => {
    const me = state.kind === 'ready' || state.kind === 'platform' ? state.me : null
    return {
      state,
      me,
      can: (permission) => !!me && me.permissions.includes(permission),
      refresh,
      signIn,
      signOut,
    }
  }, [state, refresh, signIn, signOut])

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext)
  if (!value) throw new Error('useSession outside SessionProvider')
  return value
}
