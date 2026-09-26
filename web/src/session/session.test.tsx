import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { resetCsrf } from '@/api/client'
import { ApiError } from '@/api/errors'
import { setTransport } from '@/platform/http'
import { SessionProvider, actionForError, sessionReducer, useSession } from './session'

const me = (firm: object | null = { id: 'f1', name: 'Firm', is_active: true, created_at: '' }) =>
  ({ id: 'u1', email: 'a@b.test', full_name: 'A', firm, membership_id: 'm1', role: 'STAFF', role_display: 'Staff', is_owner: false, permissions: ['client.view'] }) as never

describe('sessionReducer', () => {
  it('is ready for a person with a firm, and platform for one without', () => {
    expect(sessionReducer({ kind: 'loading' }, { type: 'me', me: me() }).kind).toBe('ready')
    expect(sessionReducer({ kind: 'loading' }, { type: 'me', me: me(null) }).kind).toBe('platform')
  })
  it('follows the sign-in sequence', () => {
    expect(sessionReducer({ kind: 'anonymous' }, { type: 'mfa', step: 'setup' })).toEqual({ kind: 'mfa', step: 'setup' })
    expect(sessionReducer({ kind: 'mfa', step: 'verify' }, { type: 'anonymous' })).toEqual({ kind: 'anonymous' })
  })
})

describe('actionForError', () => {
  it('reads the second-factor codes as the step that is missing', () => {
    expect(actionForError(new ApiError(403, { code: 'mfa_enrolment_required' }))).toEqual({ type: 'mfa', step: 'setup' })
    expect(actionForError(new ApiError(403, { code: 'mfa_required' }))).toEqual({ type: 'mfa', step: 'verify' })
  })
  it('blocks a person whose firm or membership is switched off, with the server’s reason', () => {
    expect(actionForError(new ApiError(403, { code: 'firm_inactive', detail: 'This firm has been deactivated.' }))).toEqual({
      type: 'blocked',
      detail: 'This firm has been deactivated.',
    })
  })
  it('treats anything else as signed out', () => {
    expect(actionForError(new ApiError(403, { code: 'not_authenticated' }))).toEqual({ type: 'anonymous' })
    expect(actionForError(new TypeError('network'))).toEqual({ type: 'anonymous' })
  })
})

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={client}>
      <SessionProvider>{children}</SessionProvider>
    </QueryClientProvider>
  )
}

describe('SessionProvider', () => {
  afterEach(() => {
    resetCsrf()
    setTransport((request) => fetch(request))
  })

  it('shows the enrolment step when the server says the second factor is not set up', async () => {
    setTransport(async () => json({ code: 'mfa_enrolment_required', detail: 'Set up MFA', verify_at: '/auth/mfa/setup/' }, 403))
    const { result } = renderHook(() => useSession(), { wrapper })
    await waitFor(() => expect(result.current.state).toEqual({ kind: 'mfa', step: 'setup' }))
  })

  it('shows the code step for someone who has a second factor but has not used it yet', async () => {
    setTransport(async () => json({ code: 'mfa_required', detail: 'Enter your code' }, 403))
    const { result } = renderHook(() => useSession(), { wrapper })
    await waitFor(() => expect(result.current.state).toEqual({ kind: 'mfa', step: 'verify' }))
  })

  it('offers only what the permission list allows', async () => {
    setTransport(async () => json(me()))
    const { result } = renderHook(() => useSession(), { wrapper })
    await waitFor(() => expect(result.current.state.kind).toBe('ready'))
    expect(result.current.can('client.view')).toBe(true)
    expect(result.current.can('client.create')).toBe(false)
  })
})
